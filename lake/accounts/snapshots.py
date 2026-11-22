import json
from dataclasses import dataclass

from lake.accounts.rollup import DayTotals
from lake.db import key, pack, positive_id
from lake.freeze.manifest import FrozenGroup


@dataclass(frozen=True)
class AccountGroupEntry:
    group: FrozenGroup
    first_parcel_id: str


@dataclass(frozen=True)
class DailyAccount:
    account_id: str
    revision: int
    day_key: str
    edition: int
    totals: DayTotals
    groups: tuple[AccountGroupEntry, ...]


def save_snapshot(db, account):
    db.execute(
        'INSERT INTO daily_accounts (account_id, revision, day_key, edition, totals) VALUES (?, ?, ?, ?, ?)',
        (account.account_id, account.revision, account.day_key, account.edition, pack(account.totals.to_data())),
    )
    db.executemany(
        'INSERT INTO account_groups (account_id, ordinal, group_id, body, first_parcel_id) '
        'VALUES (?, ?, ?, ?, ?)',
        (
            (account.account_id, ordinal, entry.group.group_id, pack(entry.group.to_data()), entry.first_parcel_id)
            for ordinal, entry in enumerate(account.groups)
        ),
    )


def load_snapshot(db, account_id):
    key(account_id, 'account id', 'BAD_ACCOUNT')
    row = db.execute(
        'SELECT revision, day_key, edition, totals FROM daily_accounts WHERE account_id = ?', (account_id,)
    ).fetchone()
    if row is None:
        return None
    revision, day_key, edition, totals = row
    group_rows = db.execute(
        'SELECT body, first_parcel_id FROM account_groups WHERE account_id = ? ORDER BY ordinal', (account_id,)
    )
    groups = tuple(
        AccountGroupEntry(FrozenGroup.from_data(json.loads(body)), parcel_id) for body, parcel_id in group_rows
    )
    return DailyAccount(account_id, revision, day_key, edition, DayTotals.from_data(json.loads(totals)), groups)


def load_by_revision(db, revision):
    positive_id(revision, 'revision', 'BAD_REVISION')
    row = db.execute('SELECT account_id FROM daily_accounts WHERE revision = ?', (revision,)).fetchone()
    return None if row is None else load_snapshot(db, row[0])
