from dataclasses import dataclass

from lake.db import LakeError, positive_id, sequence
from lake.intake.observations import Observation


@dataclass(frozen=True)
class GroupDefinition:
    group_id: int
    observations: tuple[Observation, ...]


def validate_group_ids(group_ids, code):
    groups = sequence(group_ids, 'group ids', code)
    if not groups:
        raise LakeError(code, 'at least one group is required')
    for group in groups:
        positive_id(group, 'group id', code)
    if len(set(groups)) != len(groups):
        raise LakeError(code, 'duplicate group id')
    return groups


def order_selection(directory, group_ids, code):
    chosen = set(validate_group_ids(group_ids, code))
    if not chosen.issubset(directory):
        raise LakeError(code, f'groups outside available set: {sorted(chosen.difference(directory))}')
    return tuple(group for group in directory if group in chosen)


def build_group_catalog(draft, group_ids):
    ordered = validate_group_ids(group_ids, 'BAD_DIRECTORY')
    rows = {group: [] for group in ordered}
    for observation in draft.observations:
        if observation.group_id not in rows:
            raise LakeError('UNDECLARED_GROUP', str(observation.group_id))
        rows[observation.group_id].append(observation)
    return tuple(GroupDefinition(group, tuple(rows[group])) for group in ordered)
