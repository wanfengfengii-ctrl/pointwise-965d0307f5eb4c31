from lake.dispatch.coverage import confirmed_groups
from lake.freeze.manifest import load_manifest


def pending_groups(db, revision):
    manifest = load_manifest(db, revision)
    confirmed = confirmed_groups(db, revision)
    return tuple(group for group in manifest.group_ids if group not in confirmed)
