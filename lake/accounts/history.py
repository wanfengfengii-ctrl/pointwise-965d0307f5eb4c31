from lake.accounts.snapshots import load_snapshot
from lake.db import LakeError
from lake.freeze.anchor import normalize_anchor
from lake.receive.binding import MODE_V2, load_binding, load_evidence
from lake.audit import build_bundle, verify_bundle


def read(db, account_id):
    """Retrieve the immutable account issued under this number, or None."""
    return load_snapshot(db, account_id)


def _account_anchor(db, account):
    binding = load_binding(db, account.revision)
    if binding is None or binding[1] != MODE_V2:
        raise LakeError('NO_AUDIT_BASIS', account.account_id)
    return normalize_anchor(binding[0])


def export_audit(db, account_id, group_ids, *, detail=False):
    """Export a limited-group audit bundle from the original account number."""
    account = load_snapshot(db, account_id)
    if account is None:
        raise LakeError('UNKNOWN_ACCOUNT', account_id)
    trusted = _account_anchor(db, account)
    evidence = load_evidence(db, account.revision, trusted['group_ids'])
    return build_bundle(account, trusted, evidence, group_ids, detail=detail)


def verify_audit(bundle, trusted_anchor, group_ids, *, detail=False):
    """Verify an audit bundle from carried values only."""
    return verify_bundle(bundle, trusted_anchor, group_ids, detail=detail)
