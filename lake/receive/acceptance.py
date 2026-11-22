from lake.db import LakeError, atomic
from lake.receive.catalog import record_catalog
from lake.receive.group_ledger import record_new_groups
from lake.receive.inspection import inspect_parcel
from lake.receive.parcel_log import load_accepted_parcel, record_accepted_parcel
from lake.receive.receipts import get_receipt


def accept(db, parcel):
    with atomic(db):
        inspection = inspect_parcel(db, parcel)
        previous = load_accepted_parcel(db, parcel.parcel_id)
        if previous is None:
            record_catalog(db, inspection.catalog)
            record_accepted_parcel(db, parcel)
            record_new_groups(db, inspection.catalog.revision, parcel.parcel_id, inspection.new_groups)
        elif previous != parcel:
            raise LakeError('PARCEL_CONFLICT', parcel.parcel_id)
    return get_receipt(db, parcel.parcel_id)
