from lake.db import LakeError, atomic
from lake.receive.binding import bind_first, check_bound, load_binding, record_evidence
from lake.receive.catalog import record_catalog
from lake.receive.group_ledger import record_new_groups
from lake.receive.inspection import inspect_parcel
from lake.receive.parcel_log import load_accepted_parcel, record_accepted_parcel
from lake.receive.receipts import get_receipt


def accept(db, parcel, *, anchor=None):
    with atomic(db):
        inspection = inspect_parcel(db, parcel)
        previous = load_accepted_parcel(db, parcel.parcel_id)
        binding = load_binding(db, inspection.catalog.revision)
        if previous is None:
            record_catalog(db, inspection.catalog)
            if binding is None:
                bind_first(db, inspection.catalog.revision, parcel, anchor)
            else:
                check_bound(db, inspection.catalog.revision, parcel, anchor)
            record_accepted_parcel(db, parcel)
            record_new_groups(db, inspection.catalog.revision, parcel.parcel_id, inspection.new_groups)
            record_evidence(db, inspection.catalog.revision, parcel)
        else:
            if binding is not None and binding[1] == 'v2':
                check_bound(db, inspection.catalog.revision, parcel, anchor)
                if previous != parcel:
                    raise LakeError('PARCEL_CONFLICT', parcel.parcel_id)
            elif parcel.is_v2 or anchor is not None:
                raise LakeError('MODE_CONFLICT', parcel.parcel_id)
            elif previous != parcel:
                raise LakeError('PARCEL_CONFLICT', parcel.parcel_id)
    return get_receipt(db, parcel.parcel_id)
