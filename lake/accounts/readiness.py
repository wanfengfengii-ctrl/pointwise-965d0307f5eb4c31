from dataclasses import dataclass

from lake.db import LakeError
from lake.receive.catalog import ReceivedCatalog, load_catalog
from lake.receive.group_ledger import ReceivedGroup, list_received_groups


@dataclass(frozen=True)
class AccountReadiness:
    catalog: ReceivedCatalog
    missing_groups: tuple[int, ...]
    received: tuple[ReceivedGroup, ...]


def assess_readiness(db, revision):
    catalog = load_catalog(db, revision)
    if catalog is None:
        raise LakeError('UNKNOWN_REVISION', str(revision))
    by_group = {entry.group.group_id: entry for entry in list_received_groups(db, revision)}
    missing = tuple(group for group in catalog.group_ids if group not in by_group)
    received = tuple(by_group[group] for group in catalog.group_ids if group in by_group)
    return AccountReadiness(catalog, missing, received)
