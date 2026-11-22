import json
from dataclasses import dataclass

from lake.db import pack
from lake.freeze.manifest import FrozenGroup


@dataclass(frozen=True)
class ReceivedGroup:
    group: FrozenGroup
    first_parcel_id: str


def _load_group(row):
    body, first_parcel_id = row
    return ReceivedGroup(FrozenGroup.from_data(json.loads(body)), first_parcel_id)


def find_group(db, revision, group_id):
    row = db.execute(
        'SELECT body, first_parcel_id FROM received_groups WHERE revision = ? AND group_id = ?',
        (revision, group_id),
    ).fetchone()
    return None if row is None else _load_group(row)


def record_new_groups(db, revision, parcel_id, groups):
    db.executemany(
        'INSERT INTO received_groups (revision, group_id, body, first_parcel_id) VALUES (?, ?, ?, ?)',
        ((revision, group.group_id, pack(group.to_data()), parcel_id) for group in groups),
    )


def list_received_groups(db, revision):
    rows = db.execute(
        'SELECT body, first_parcel_id FROM received_groups WHERE revision = ? ORDER BY group_id', (revision,)
    )
    return tuple(_load_group(row) for row in rows)
