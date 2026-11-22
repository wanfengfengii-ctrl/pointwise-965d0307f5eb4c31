from dataclasses import dataclass

from lake.db import LakeError, key, positive_id
from lake.dispatch.parcels import DeliveryParcel
from lake.freeze.groups import order_selection
from lake.freeze.manifest import FrozenGroup, FrozenManifest
from lake.freeze.measures import GroupMeasure, measure_group
from lake.intake.observations import Observation
from lake.receive.catalog import ReceivedCatalog, load_catalog
from lake.receive.group_ledger import find_group


@dataclass(frozen=True)
class ParcelInspection:
    catalog: ReceivedCatalog
    covered_group_ids: tuple[int, ...]
    new_groups: tuple[FrozenGroup, ...]


def _validate_group(group):
    code = 'BAD_GROUP'
    positive_id(group.group_id, 'group id', code)
    if type(group.observations) is not tuple or type(group.measure) is not GroupMeasure:
        raise LakeError(code, 'invalid group body')
    positions = {}
    for observation in group.observations:
        if not isinstance(observation, Observation):
            raise LakeError(code, 'invalid observation')
        observation.validate()
        if observation.group_id != group.group_id:
            raise LakeError(code, 'observation belongs to another group')
        last_position = positions.get(observation.batch_id, 0)
        if observation.position <= last_position:
            raise LakeError(code, 'repeated or out-of-order batch position')
        positions[observation.batch_id] = observation.position
    group.measure.validate()
    if group.measure != measure_group(group.observations):
        raise LakeError('MEASURE_MISMATCH', str(group.group_id))


def inspect_parcel(db, parcel):
    code = 'BAD_PARCEL'
    if not isinstance(parcel, DeliveryParcel) or not isinstance(parcel.manifest, FrozenManifest):
        raise LakeError(code, 'invalid parcel or manifest')
    key(parcel.parcel_id, 'parcel id', code)
    parcel.manifest.validate()
    if type(parcel.groups) is not tuple or any(not isinstance(group, FrozenGroup) for group in parcel.groups):
        raise LakeError(code, 'invalid group material')
    catalog = ReceivedCatalog.from_manifest(parcel.manifest)
    covered = order_selection(catalog.group_ids, parcel.group_ids, code)
    if covered != parcel.group_ids:
        raise LakeError(code, 'groups must follow the manifest order')
    existing = load_catalog(db, catalog.revision)
    if existing is not None and existing != catalog:
        raise LakeError('CATALOG_CONFLICT', str(catalog.revision))
    new_groups = []
    for group in parcel.groups:
        _validate_group(group)
        previous = find_group(db, catalog.revision, group.group_id)
        if previous is None:
            new_groups.append(group)
        elif previous.group != group:
            raise LakeError('GROUP_CONFLICT', str(group.group_id))
    return ParcelInspection(catalog, covered, tuple(new_groups))
