import json

from lake.audit import verify_parcel_material
from lake.db import LakeError, pack
from lake.freeze.anchor import normalize_anchor


MODE_V1 = 'v1'
MODE_V2 = 'v2'


def load_binding(db, revision):
    row = db.execute(
        'SELECT anchor, mode FROM catalog_anchors WHERE revision = ?', (revision,)
    ).fetchone()
    if row is None:
        return None
    anchor, mode = row
    return (normalize_anchor(json.loads(anchor)) if mode == MODE_V2 else None, mode)


def bind_first(db, revision, parcel, anchor):
    """Bind the edition's mode and, for V2, its trusted anchor before first receipt."""
    if parcel.is_v2:
        if anchor is None:
            raise LakeError('MISSING_ANCHOR', parcel.parcel_id)
        trusted = normalize_anchor(anchor)
        verify_parcel_material(parcel, trusted)
        db.execute(
            'INSERT INTO catalog_anchors (revision, anchor, mode) VALUES (?, ?, ?)',
            (revision, pack(trusted), MODE_V2),
        )
        return
    if anchor is not None:
        raise LakeError('UNEXPECTED_ANCHOR', parcel.parcel_id)
    db.execute(
        'INSERT INTO catalog_anchors (revision, anchor, mode) VALUES (?, ?, ?)',
        (revision, 'null', MODE_V1),
    )


def check_bound(db, revision, parcel, anchor):
    binding = load_binding(db, revision)
    if binding is None:
        raise LakeError('UNKNOWN_REVISION', str(revision))
    trusted, mode = binding
    if mode == MODE_V1:
        if parcel.is_v2 or anchor is not None:
            raise LakeError('MODE_CONFLICT', str(revision))
        return
    if not parcel.is_v2:
        raise LakeError('MODE_CONFLICT', str(revision))
    if anchor is None:
        raise LakeError('MISSING_ANCHOR', parcel.parcel_id)
    if normalize_anchor(anchor) != trusted:
        raise LakeError('ANCHOR_MISMATCH', str(revision))
    verify_parcel_material(parcel, trusted)


def record_evidence(db, revision, parcel):
    if not parcel.is_v2:
        return
    db.executemany(
        'INSERT INTO received_evidence (revision, group_id, body) VALUES (?, ?, ?) '
        'ON CONFLICT (revision, group_id) DO NOTHING',
        ((revision, group_id, pack(body)) for group_id, body in parcel.evidence),
    )


def load_evidence(db, revision, group_ids):
    wanted = set(group_ids)
    rows = db.execute(
        'SELECT group_id, body FROM received_evidence WHERE revision = ?', (revision,)
    )
    found = {group_id: json.loads(body) for group_id, body in rows if group_id in wanted}
    if set(found) != wanted:
        raise LakeError('MISSING_EVIDENCE', str(revision))
    return found
