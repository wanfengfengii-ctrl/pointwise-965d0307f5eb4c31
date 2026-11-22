"""Database-free V2 audit material: anchor redaction, parcel and bundle checks.

Everything here works from carried values only.  The acceptance path uses the
same primitives as the detached verifier so a bundle and a parcel are judged by
the same frozen facts.
"""
import hashlib

from lake.db import LakeError, pack, positive_id, require_fields, sequence
from lake.freeze.anchor import (
    BUNDLE_FORMAT,
    canonical_salt,
    detail_commitment,
    measure_commitment,
    normalize_anchor,
    validate_evidence,
)
from lake.freeze.manifest import FrozenManifest
from lake.freeze.measures import GroupMeasure, measure_group
from lake.intake.observations import Observation

PROOF_FORMAT = 'lake-audit-proof-v2'


def _hide(revision, edition, ordinal, group_id, kind):
    return hashlib.sha256(pack({
        'domain': 'lake.audit.hide.v2',
        'kind': kind,
        'revision': revision,
        'edition': edition,
        'ordinal': ordinal,
        'group_id': group_id,
    }).encode('utf-8')).hexdigest()


def redact_anchor(anchor, carried_ids):
    """Return a parcel-safe anchor that hides every group not carried."""
    normalized = normalize_anchor(anchor)
    carried = set(carried_ids)
    measure = {}
    detail = {}
    for ordinal, group_id in enumerate(normalized['group_ids'], start=1):
        text = str(group_id)
        if group_id in carried:
            measure[text] = normalized['measure_commitments'][text]
            detail[text] = normalized['detail_commitments'][text]
        else:
            measure[text] = _hide(normalized['revision'], normalized['edition'], ordinal, group_id, 'measure')
            detail[text] = _hide(normalized['revision'], normalized['edition'], ordinal, group_id, 'detail')
    return {
        'format': normalized['format'],
        'revision': normalized['revision'],
        'day_key': normalized['day_key'],
        'edition': normalized['edition'],
        'group_ids': list(normalized['group_ids']),
        'measure_commitments': measure,
        'detail_commitments': detail,
    }


def _same_identity(carried, trusted):
    return (
        carried['revision'] == trusted['revision']
        and carried['day_key'] == trusted['day_key']
        and carried['edition'] == trusted['edition']
        and carried['group_ids'] == trusted['group_ids']
    )


def verify_parcel_material(parcel, trusted_anchor):
    """Check a V2 parcel against a separately obtained anchor.

    The parcel's redacted anchor must equal what the trusted anchor redacts to
    for exactly the carried groups, and every carried group must open both its
    measure and detail commitment under the anchored ordinal and group number.
    """
    code = 'PARCEL_ANCHOR_MISMATCH'
    trusted = normalize_anchor(trusted_anchor)
    if parcel.anchor is None:
        raise LakeError('MISSING_ANCHOR', parcel.parcel_id)
    carried = normalize_anchor(parcel.anchor)
    if not _same_identity(carried, trusted):
        raise LakeError(code, 'parcel directory does not match the trusted anchor')
    openings = dict(parcel.evidence)
    wanted = tuple(parcel.group_ids)
    if len(openings) != len(parcel.evidence) or tuple(sorted(openings)) != tuple(sorted(wanted)):
        raise LakeError('BAD_EVIDENCE', 'parcel evidence does not cover exactly its groups')
    expected = redact_anchor(trusted, wanted)
    if carried != expected:
        raise LakeError(code, 'parcel anchor does not match the trusted anchor')
    directory = trusted['group_ids']
    manifest = parcel.manifest
    if (manifest.revision, manifest.day_key, manifest.edition) != (
        trusted['revision'], trusted['day_key'], trusted['edition']
    ) or tuple(manifest.group_ids) != tuple(directory):
        raise LakeError(code, 'parcel manifest does not match the trusted anchor')
    wanted = tuple(parcel.group_ids)
    if not wanted or tuple(group for group in directory if group in set(wanted)) != wanted:
        raise LakeError('BAD_PARCEL', 'groups must follow the manifest order')
    by_group = {group.group_id: group for group in parcel.groups}
    if tuple(group.group_id for group in parcel.groups) != wanted:
        raise LakeError('BAD_PARCEL', 'groups must follow the manifest order')
    for group_id in wanted:
        ordinal = directory.index(group_id) + 1
        opening = validate_evidence(openings[group_id])
        group = by_group[group_id]
        measure_data = group.measure.to_data()
        observations = [row.to_data() for row in group.observations]
        if measure_commitment(
            trusted['revision'], trusted['day_key'], trusted['edition'], ordinal,
            group_id, opening['measure_salt'], measure_data,
        ) != trusted['measure_commitments'][str(group_id)]:
            raise LakeError('EVIDENCE_MISMATCH', str(group_id))
        if detail_commitment(
            trusted['revision'], trusted['day_key'], trusted['edition'], ordinal,
            group_id, opening['detail_salt'], measure_data, observations,
        ) != trusted['detail_commitments'][str(group_id)]:
            raise LakeError('EVIDENCE_MISMATCH', str(group_id))


def _ordered_expected(trusted, group_ids):
    code = 'BAD_SELECTION'
    chosen = sequence(group_ids, 'group ids', code)
    if not chosen:
        raise LakeError(code, 'at least one group is required')
    for group in chosen:
        positive_id(group, 'group id', code)
    if len(set(chosen)) != len(chosen):
        raise LakeError(code, 'duplicate group id')
    directory = trusted['group_ids']
    if not set(chosen).issubset(directory):
        raise LakeError(code, 'groups outside the anchored directory')
    return tuple(group for group in directory if group in set(chosen))


def build_bundle(account, trusted_anchor, evidence, group_ids, *, detail=False):
    """Assemble an audit bundle for the requested groups in frozen order."""
    if type(detail) is not bool:
        raise LakeError('BAD_SELECTION', 'detail requires a boolean')
    trusted = normalize_anchor(trusted_anchor)
    chosen = _ordered_expected(trusted, group_ids)
    entries = {entry.group.group_id: entry for entry in account.groups}
    if any(group not in entries for group in chosen):
        raise LakeError('BAD_SELECTION', 'account does not carry the requested groups')
    groups = []
    openings = {}
    for group_id in chosen:
        ordinal = trusted['group_ids'].index(group_id) + 1
        group = entries[group_id].group
        item = {
            'ordinal': ordinal,
            'group_id': group_id,
            'measure': group.measure.to_data(),
        }
        if detail:
            item['observations'] = [row.to_data() for row in group.observations]
        groups.append(item)
        opening = validate_evidence(evidence[group_id])
        key = 'detail_salt' if detail else 'measure_salt'
        openings[str(group_id)] = {key: opening[key]}
    proof = {
        'format': PROOF_FORMAT,
        'revision': trusted['revision'],
        'day_key': trusted['day_key'],
        'edition': trusted['edition'],
        'detail': detail,
        'group_ids': list(chosen),
        'openings': openings,
    }
    return {
        'format': BUNDLE_FORMAT,
        'manifest': FrozenManifest(
            account.revision, account.day_key, account.edition,
            tuple(entry.group.group_id for entry in account.groups),
        ).to_data(),
        'detail': detail,
        'groups': groups,
        'proof': proof,
    }


_BUNDLE_FIELDS = ('format', 'manifest', 'detail', 'groups', 'proof')
_GROUP_FIELDS = ('ordinal', 'group_id', 'measure')
_DETAIL_GROUP_FIELDS = ('ordinal', 'group_id', 'measure', 'observations')
_PROOF_FIELDS = ('format', 'revision', 'day_key', 'edition', 'detail', 'group_ids', 'openings')


def verify_bundle(bundle, trusted_anchor, group_ids, *, detail=False):
    """Independently check a bundle against a trusted anchor and expectations."""
    code = 'BAD_BUNDLE'
    if type(detail) is not bool:
        raise LakeError(code, 'expected detail requires a boolean')
    trusted = normalize_anchor(trusted_anchor)
    chosen = _ordered_expected(trusted, group_ids)
    require_fields(bundle, _BUNDLE_FIELDS, code)
    if bundle['format'] != BUNDLE_FORMAT:
        raise LakeError(code, 'unsupported bundle format')
    if type(bundle['detail']) is not bool:
        raise LakeError(code, 'detail requires a boolean')
    if bundle['detail'] != detail:
        raise LakeError('WRONG_DETAIL', 'bundle granularity differs from the expected one')
    manifest = FrozenManifest.from_data(bundle['manifest'])
    if (manifest.revision, manifest.day_key, manifest.edition) != (
        trusted['revision'], trusted['day_key'], trusted['edition']
    ) or tuple(manifest.group_ids) != tuple(trusted['group_ids']):
        raise LakeError('WRONG_REVISION', 'bundle manifest differs from the trusted anchor')
    proof = bundle['proof']
    require_fields(proof, _PROOF_FIELDS, code)
    if proof['format'] != PROOF_FORMAT:
        raise LakeError(code, 'unsupported proof format')
    for field in ('revision', 'day_key', 'edition'):
        if proof[field] != trusted[field]:
            raise LakeError('WRONG_REVISION', f'proof {field} differs from the trusted anchor')
    if type(proof['detail']) is not bool or proof['detail'] != detail:
        raise LakeError('WRONG_DETAIL', 'proof granularity differs from the expected one')
    disclosed = tuple(proof['group_ids'])
    if set(disclosed) != set(chosen) or len(disclosed) != len(chosen):
        raise LakeError('WRONG_SCOPE', 'bundle scope differs from the expected groups')
    openings = proof['openings']
    if type(openings) is not dict or set(openings.keys()) != {str(group) for group in chosen}:
        raise LakeError('WRONG_SCOPE', 'bundle openings do not match the expected groups')

    items = sequence(bundle['groups'], 'bundle groups', code)
    if len(items) != len(chosen):
        raise LakeError('WRONG_SCOPE', 'bundle groups do not match the expected groups')
    expected_fields = _DETAIL_GROUP_FIELDS if detail else _GROUP_FIELDS
    results = []
    directory = trusted['group_ids']
    last_ordinal = 0
    for item, group_id in zip(items, chosen):
        require_fields(item, expected_fields, code)
        ordinal = item['ordinal']
        if type(ordinal) is not int or ordinal != directory.index(group_id) + 1:
            raise LakeError('WRONG_POSITION', f'group {group_id} is not at its frozen ordinal')
        if ordinal <= last_ordinal:
            raise LakeError('WRONG_POSITION', 'groups are not in frozen directory order')
        last_ordinal = ordinal
        if type(item['group_id']) is not int or item['group_id'] != group_id:
            raise LakeError('WRONG_SCOPE', 'bundle group order differs from the expected scope')
        measure = GroupMeasure.from_data(item['measure'])
        observations = ()
        if detail:
            observations = tuple(
                Observation.from_data(row) for row in sequence(item['observations'], 'observations', code)
            )
            for row in observations:
                if row.group_id != group_id:
                    raise LakeError(code, 'observation belongs to another group')
            if measure != measure_group(observations):
                raise LakeError('MEASURE_MISMATCH', str(group_id))
        opening = openings[str(group_id)]
        salt_field = 'detail_salt' if detail else 'measure_salt'
        require_fields(opening, (salt_field,), code)
        salt = canonical_salt(opening[salt_field], salt_field, code)
        measure_data = measure.to_data()
        observations_data = [row.to_data() for row in observations]
        if detail:
            actual = detail_commitment(
                trusted['revision'], trusted['day_key'], trusted['edition'], ordinal,
                group_id, salt, measure_data, observations_data,
            )
            if actual != trusted['detail_commitments'][str(group_id)]:
                raise LakeError('EVIDENCE_MISMATCH', str(group_id))
        else:
            actual = measure_commitment(
                trusted['revision'], trusted['day_key'], trusted['edition'], ordinal,
                group_id, salt, measure_data,
            )
            if actual != trusted['measure_commitments'][str(group_id)]:
                raise LakeError('EVIDENCE_MISMATCH', str(group_id))
        results.append(item)
    return results
