import json
from dataclasses import dataclass

from lake.audit import redact_anchor
from lake.db import LakeError, atomic, key, pack, require_fields, sequence
from lake.freeze.anchor import PARCEL_FORMAT, load_anchor, load_evidence, validate_evidence
from lake.dispatch.plans import load_wave
from lake.freeze.groups import order_selection
from lake.freeze.manifest import FrozenGroup, FrozenManifest, load_frozen_groups, load_manifest


@dataclass(frozen=True)
class DeliveryParcel:
    parcel_id: str
    manifest: FrozenManifest
    groups: tuple[FrozenGroup, ...]
    anchor: dict | None = None
    evidence: tuple = ()

    @property
    def group_ids(self):
        return tuple(group.group_id for group in self.groups)

    @property
    def is_v2(self):
        return self.anchor is not None

    def to_json(self):
        data = {
            'parcel_id': self.parcel_id,
            'manifest': self.manifest.to_data(),
            'groups': [group.to_data() for group in self.groups],
        }
        if self.anchor is not None:
            data['format'] = PARCEL_FORMAT
            data['anchor'] = self.anchor
            data['evidence'] = {str(group): dict(body) for group, body in self.evidence}
        return pack(data)

    @classmethod
    def from_json(cls, text):
        code = 'BAD_PARCEL'
        if type(text) is not str:
            raise LakeError(code, 'parcel JSON requires text')
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise LakeError(code, 'invalid parcel JSON') from exc
        if type(data) is not dict:
            raise LakeError(code, 'parcel JSON requires an object')
        if 'format' not in data:
            require_fields(data, ('parcel_id', 'manifest', 'groups'), code)
            return cls(
                key(data['parcel_id'], 'parcel id', code),
                FrozenManifest.from_data(data['manifest']),
                tuple(FrozenGroup.from_data(group) for group in sequence(data['groups'], 'groups', code)),
            )
        require_fields(data, ('format', 'parcel_id', 'manifest', 'groups', 'anchor', 'evidence'), code)
        if data['format'] != PARCEL_FORMAT:
            raise LakeError(code, 'unsupported parcel format')
        raw_evidence = data['evidence']
        if type(raw_evidence) is not dict:
            raise LakeError(code, 'evidence requires an object')
        evidence = []
        for name, body in raw_evidence.items():
            try:
                group_id = int(name, 10)
            except (TypeError, ValueError) as exc:
                raise LakeError(code, 'invalid evidence group') from exc
            if str(group_id) != name:
                raise LakeError(code, 'noncanonical evidence group')
            evidence.append((group_id, validate_evidence(body)))
        return cls(
            key(data['parcel_id'], 'parcel id', code),
            FrozenManifest.from_data(data['manifest']),
            tuple(FrozenGroup.from_data(group) for group in sequence(data['groups'], 'groups', code)),
            raw_anchor(data['anchor'], code),
            tuple(evidence),
        )


def raw_anchor(value, code='BAD_PARCEL'):
    if type(value) is not dict:
        raise LakeError(code, 'anchor requires an object')
    return value


def _find_parcel(db, parcel_id):
    row = db.execute('SELECT body FROM issued_parcels WHERE parcel_id = ?', (parcel_id,)).fetchone()
    return None if row is None else DeliveryParcel.from_json(row[0])


def load_parcel(db, parcel_id):
    key(parcel_id, 'parcel id', 'BAD_PARCEL')
    parcel = _find_parcel(db, parcel_id)
    if parcel is None:
        raise LakeError('UNKNOWN_PARCEL', parcel_id)
    return parcel


def _compose_v2(db, revision, parcel_id, ordered):
    anchor = load_anchor(db, revision)
    if anchor is None:
        raise LakeError('NO_ANCHOR', str(revision))
    manifest = load_manifest(db, revision)
    groups = load_frozen_groups(db, revision, ordered)
    evidence = load_evidence(db, revision, ordered)
    return DeliveryParcel(
        parcel_id, manifest, groups,
        redact_anchor(anchor, ordered),
        tuple((group_id, evidence[group_id]) for group_id in ordered),
    )


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
        anchored = load_anchor(db, revision)
        if anchored is None:
            parcel = DeliveryParcel(parcel_id, manifest, load_frozen_groups(db, revision, ordered))
            db.execute(
                'INSERT INTO issued_parcels (parcel_id, revision, body) VALUES (?, ?, ?)',
                (parcel_id, revision, parcel.to_json()),
            )
            return parcel
        expected = _compose_v2(db, revision, parcel_id, ordered)
        db.execute(
            'INSERT INTO issued_parcels (parcel_id, revision, body) VALUES (?, ?, ?)',
            (parcel_id, revision, expected.to_json()),
        )
    return expected
