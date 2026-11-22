from lake.db import LakeError, atomic, positive_id
from lake.dispatch.backlog import pending_groups
from lake.dispatch.coverage import record_coverage
from lake.dispatch.parcels import load_parcel
from lake.freeze.groups import validate_group_ids
from lake.receive.receipts import Receipt


def confirm(db, receipt):
    code = 'BAD_RECEIPT'
    if not isinstance(receipt, Receipt):
        raise LakeError(code, 'expected Receipt')
    positive_id(receipt.revision, 'revision', code)
    covered = validate_group_ids(receipt.group_ids, code)
    with atomic(db):
        parcel = load_parcel(db, receipt.parcel_id)
        if receipt.revision != parcel.manifest.revision or covered != parcel.group_ids:
            raise LakeError(code, 'receipt does not match the issued parcel')
        record_coverage(db, receipt.revision, covered)
        return pending_groups(db, receipt.revision)
