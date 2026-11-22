from dataclasses import dataclass

from lake.db import LakeError
from lake.receive.parcel_log import load_accepted_parcel


@dataclass(frozen=True)
class Receipt:
    parcel_id: str
    revision: int
    group_ids: tuple[int, ...]


def get_receipt(db, parcel_id):
    parcel = load_accepted_parcel(db, parcel_id)
    if parcel is None:
        raise LakeError('UNKNOWN_RECEIPT', parcel_id)
    return Receipt(parcel.parcel_id, parcel.manifest.revision, parcel.group_ids)
