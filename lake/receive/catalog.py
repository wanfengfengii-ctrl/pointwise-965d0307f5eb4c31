import json
from dataclasses import dataclass

from lake.db import pack, positive_id
from lake.freeze.manifest import FrozenManifest


@dataclass(frozen=True)
class ReceivedCatalog:
    revision: int
    day_key: str
    edition: int
    group_ids: tuple[int, ...]

    @classmethod
    def from_manifest(cls, manifest: FrozenManifest):
        return cls(manifest.revision, manifest.day_key, manifest.edition, manifest.group_ids)


def load_catalog(db, revision):
    positive_id(revision, 'revision', 'BAD_REVISION')
    row = db.execute(
        'SELECT day_key, edition, group_ids FROM received_catalogs WHERE revision = ?', (revision,)
    ).fetchone()
    if row is None:
        return None
    day_key, edition, group_ids = row
    return ReceivedCatalog(revision, day_key, edition, tuple(json.loads(group_ids)))


def record_catalog(db, catalog):
    db.execute(
        'INSERT INTO received_catalogs (revision, day_key, edition, group_ids) VALUES (?, ?, ?, ?) '
        'ON CONFLICT (revision) DO NOTHING',
        (catalog.revision, catalog.day_key, catalog.edition, pack(catalog.group_ids)),
    )
