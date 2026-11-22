from lake.db import atomic
from lake.freeze.groups import build_group_catalog
from lake.freeze.manifest import FrozenGroup, save_manifest
from lake.freeze.measures import measure_group
from lake.intake.day_assembly import assemble_day


def freeze(db, day_key, batch_ids, group_ids):
    with atomic(db):
        draft = assemble_day(db, day_key, batch_ids)
        definitions = build_group_catalog(draft, group_ids)
        groups = tuple(
            FrozenGroup(group.group_id, group.observations, measure_group(group.observations))
            for group in definitions
        )
        return save_manifest(db, day_key, groups)
