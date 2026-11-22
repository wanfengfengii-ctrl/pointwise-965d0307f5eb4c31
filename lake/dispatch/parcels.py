import json
from dataclasses import dataclass

from lake.db import LakeError, atomic, key, pack, require_fields, sequence
from lake.dispatch.plans import load_wave
from lake.freeze.groups import order_selection
from lake.freeze.manifest import FrozenGroup, FrozenManifest, load_frozen_groups, load_manifest


@dataclass(frozen=True)
class DeliveryParcel:
    parcel_id: str
    manifest: FrozenManifest
    groups: tuple[FrozenGroup, ...]

    @property
    def group_ids(self):
        return tuple(group.group_id for group in self.groups)

    def to_json(self):
        return pack({
            'parcel_id': self.parcel_id,
            'manifest': self.manifest.to_data(),
            'groups': [group.to_data() for group in self.groups],
        })

    @classmethod
    def from_json(cls, text):
        code = 'BAD_PARCEL'
        if type(text) is not str:
            raise LakeError(code, 'parcel JSON requires text')
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise LakeError(code, 'invalid parcel JSON') from exc
        require_fields(data, ('parcel_id', 'manifest', 'groups'), code)
        return cls(
            key(data['parcel_id'], 'parcel id', code),
            FrozenManifest.from_data(data['manifest']),
            tuple(FrozenGroup.from_data(group) for group in sequence(data['groups'], 'groups', code)),
        )


def _find_parcel(db, parcel_id):
    row = db.execute('SELECT body FROM issued_parcels WHERE parcel_id = ?', (parcel_id,)).fetchone()
    return None if row is None else DeliveryParcel.from_json(row[0])


def load_parcel(db, parcel_id):
    key(parcel_id, 'parcel id', 'BAD_PARCEL')
    parcel = _find_parcel(db, parcel_id)
    if parcel is None:
        raise LakeError('UNKNOWN_PARCEL', parcel_id)
    return parcel


def dispatch(db, revision, parcel_id, *, group_ids=None, wave=None):
    key(parcel_id, 'parcel id', 'BAD_PARCEL')
    if (group_ids is None) == (wave is None):
        raise LakeError('BAD_SELECTION', 'supply either group ids or a wave')
    with atomic(db):
        manifest = load_manifest(db, revision)
        selection = group_ids if wave is None else load_wave(db, revision, wave)
        ordered = order_selection(manifest.group_ids, selection, 'BAD_SELECTION')
        existing = _find_parcel(db, parcel_id)
        if existing is not None:
            if existing.manifest.revision != revision or existing.group_ids != ordered:
                raise LakeError('PARCEL_CONFLICT', parcel_id)
            return existing
        parcel = DeliveryParcel(parcel_id, manifest, load_frozen_groups(db, revision, ordered))
        db.execute(
            'INSERT INTO issued_parcels (parcel_id, revision, body) VALUES (?, ?, ?)',
            (parcel_id, revision, parcel.to_json()),
        )
    return parcel
