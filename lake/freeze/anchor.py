"""Freeze-time audit anchors and per-group evidence for the V2 audit.

An anchor fixes the complete directory identity of one immutable revision plus
one salted commitment per group for each disclosure granularity.  Commitments
are one-way and every salt is independent, so holding the anchor for one
revision never lets a holder check a guess about a group whose evidence was
not disclosed with the material for that group.
"""
import hashlib
import json
import secrets

from lake.db import LakeError, key, pack, positive_id, require_fields, sequence

ANCHOR_FORMAT = 'lake-audit-anchor-v2'
BUNDLE_FORMAT = 'lake-audit-bundle-v2'
PARCEL_FORMAT = 'lake-parcel-v2'

_ANCHOR_FIELDS = (
    'format', 'revision', 'day_key', 'edition', 'group_ids',
    'measure_commitments', 'detail_commitments',
)


def _canonical_hex(value, field, code='BAD_ANCHOR'):
    if type(value) is not str or len(value) != 64:
        raise LakeError(code, f'invalid {field}')
    try:
        number = int(value, 16)
    except ValueError as exc:
        raise LakeError(code, f'invalid {field}') from exc
    if format(number, '064x') != value:
        raise LakeError(code, f'noncanonical {field}')
    return value


canonical_salt = _canonical_hex


def _group_ids(value, code='BAD_ANCHOR'):
    groups = sequence(value, 'anchor groups', code)
    if not groups:
        raise LakeError(code, 'anchor requires at least one group')
    for group in groups:
        positive_id(group, 'group id', code)
    if len(set(groups)) != len(groups):
        raise LakeError(code, 'duplicate group id in anchor')
    return tuple(groups)


def _commitments(value, groups, field, code='BAD_ANCHOR'):
    if type(value) is not dict:
        raise LakeError(code, f'{field} requires an object')
    expected = {str(group) for group in groups}
    if set(value.keys()) != expected:
        raise LakeError(code, f'{field} does not cover the directory')
    for commitment in value.values():
        _canonical_hex(commitment, field, code)
    return {str(group): value[str(group)] for group in groups}


def _digest(domain, revision, day_key, edition, ordinal, group_id, salt, body):
    return hashlib.sha256(pack({
        'domain': domain,
        'revision': revision,
        'day_key': day_key,
        'edition': edition,
        'ordinal': ordinal,
        'group_id': group_id,
        'salt': salt,
        'body': body,
    }).encode('utf-8')).hexdigest()


def measure_commitment(revision, day_key, edition, ordinal, group_id, salt, measure_data):
    return _digest(
        'lake.audit.measure.v2', revision, day_key, edition, ordinal, group_id, salt,
        {'measure': measure_data},
    )


def detail_commitment(revision, day_key, edition, ordinal, group_id, salt, measure_data, observations_data):
    return _digest(
        'lake.audit.detail.v2', revision, day_key, edition, ordinal, group_id, salt,
        {'measure': measure_data, 'observations': list(observations_data)},
    )


def build_anchor(manifest, groups):
    """Return the anchor and the per-group opening material for a frozen edition."""
    directory = tuple(manifest.group_ids)
    if len(groups) != len(directory):
        raise LakeError('BAD_DIRECTORY', 'frozen groups do not match the directory')
    measure_commitments = {}
    detail_commitments = {}
    evidence = {}
    for ordinal, (group, group_id) in enumerate(zip(groups, directory), start=1):
        if group.group_id != group_id:
            raise LakeError('BAD_DIRECTORY', 'frozen groups do not match the directory')
        measure_salt = secrets.token_hex(32)
        detail_salt = secrets.token_hex(32)
        measure_data = group.measure.to_data()
        observations = [row.to_data() for row in group.observations]
        measure_commitments[str(group_id)] = measure_commitment(
            manifest.revision, manifest.day_key, manifest.edition, ordinal,
            group_id, measure_salt, measure_data,
        )
        detail_commitments[str(group_id)] = detail_commitment(
            manifest.revision, manifest.day_key, manifest.edition, ordinal,
            group_id, detail_salt, measure_data, observations,
        )
        evidence[group_id] = {
            'measure_salt': measure_salt,
            'detail_salt': detail_salt,
        }
    anchor = {
        'format': ANCHOR_FORMAT,
        'revision': manifest.revision,
        'day_key': manifest.day_key,
        'edition': manifest.edition,
        'group_ids': list(directory),
        'measure_commitments': measure_commitments,
        'detail_commitments': detail_commitments,
    }
    return anchor, evidence


def normalize_anchor(anchor, code='BAD_ANCHOR'):
    """Validate an anchor dict and return its canonical JSON-friendly form."""
    require_fields(anchor, _ANCHOR_FIELDS, code)
    if anchor['format'] != ANCHOR_FORMAT:
        raise LakeError(code, 'unsupported anchor format')
    revision = positive_id(anchor['revision'], 'revision', code)
    day_key = key(anchor['day_key'], 'day key', code)
    edition = positive_id(anchor['edition'], 'edition', code)
    groups = _group_ids(anchor['group_ids'], code)
    measure = _commitments(anchor['measure_commitments'], groups, 'measure commitments', code)
    detail = _commitments(anchor['detail_commitments'], groups, 'detail commitments', code)
    return {
        'format': ANCHOR_FORMAT,
        'revision': revision,
        'day_key': day_key,
        'edition': edition,
        'group_ids': list(groups),
        'measure_commitments': measure,
        'detail_commitments': detail,
    }


def pack_anchor(anchor):
    return pack(normalize_anchor(anchor))


def save_anchor(db, anchor, evidence):
    db.execute(
        'INSERT INTO revision_anchors (revision, anchor) VALUES (?, ?)',
        (anchor['revision'], pack_anchor(anchor)),
    )
    db.executemany(
        'INSERT INTO frozen_evidence (revision, group_id, body) VALUES (?, ?, ?)',
        (
            (anchor['revision'], group_id, pack(body))
            for group_id, body in evidence.items()
        ),
    )


def load_anchor(db, revision):
    row = db.execute(
        'SELECT anchor FROM revision_anchors WHERE revision = ?', (revision,)
    ).fetchone()
    return None if row is None else normalize_anchor(json.loads(row[0]))


def load_evidence(db, revision, group_ids):
    wanted = set(group_ids)
    rows = db.execute(
        'SELECT group_id, body FROM frozen_evidence WHERE revision = ?', (revision,)
    )
    found = {group_id: json.loads(body) for group_id, body in rows if group_id in wanted}
    if set(found) != wanted:
        raise LakeError('MISSING_EVIDENCE', str(revision))
    for body in found.values():
        validate_evidence(body)
    return found


def validate_evidence(body):
    """Validate one stored or carried per-group opening record."""
    require_fields(body, ('measure_salt', 'detail_salt'), 'BAD_ANCHOR')
    _canonical_hex(body['measure_salt'], 'measure salt')
    _canonical_hex(body['detail_salt'], 'detail salt')
    return {'measure_salt': body['measure_salt'], 'detail_salt': body['detail_salt']}
