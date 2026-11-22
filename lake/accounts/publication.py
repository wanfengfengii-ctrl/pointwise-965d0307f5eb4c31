from dataclasses import dataclass

from lake.accounts.readiness import assess_readiness
from lake.accounts.rollup import rollup_groups
from lake.accounts.snapshots import AccountGroupEntry, DailyAccount, load_by_revision, save_snapshot
from lake.db import atomic


@dataclass(frozen=True)
class PostResult:
    account_id: str | None
    missing_groups: tuple[int, ...]


def post(db, revision):
    with atomic(db):
        previous = load_by_revision(db, revision)
        if previous is not None:
            return PostResult(previous.account_id, ())
        readiness = assess_readiness(db, revision)
        if readiness.missing_groups:
            return PostResult(None, readiness.missing_groups)
        catalog = readiness.catalog
        entries = tuple(AccountGroupEntry(entry.group, entry.first_parcel_id) for entry in readiness.received)
        account = DailyAccount(
            f'DW-{revision:06d}', revision, catalog.day_key, catalog.edition,
            rollup_groups(readiness.received), entries,
        )
        save_snapshot(db, account)
        return PostResult(account.account_id, ())
