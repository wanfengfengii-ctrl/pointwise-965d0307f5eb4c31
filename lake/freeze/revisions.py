from lake.db import LakeError, atomic
from lake.freeze.anchor import build_anchor, save_anchor
from lake.freeze.groups import build_group_catalog
from lake.freeze.manifest import FrozenGroup, save_manifest
from lake.freeze.measures import measure_group
from lake.intake.day_assembly import assemble_day


def freeze(db, day_key, batch_ids, group_ids, *, with_anchor=False):
    if type(with_anchor) is not bool:
        raise LakeError('BAD_ANCHOR', 'with_anchor requires a boolean')
    with atomic(db):
        draft = assemble_day(db, day_key, batch_ids)
        definitions = build_group_catalog(draft, group_ids)
        groups = tuple(
            FrozenGroup(group.group_id, group.observations, measure_group(group.observations))
            for group in definitions
        )
        manifest = save_manifest(db, day_key, groups)
        if not with_anchor:
            return manifest
        anchor, evidence = build_anchor(manifest, groups)
        save_anchor(db, anchor, evidence)
    return manifest, anchor
