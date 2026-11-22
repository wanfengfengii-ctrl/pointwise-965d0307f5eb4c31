import json
from dataclasses import dataclass

from lake.db import LakeError, key, pack, positive_id, require_fields, sequence
from lake.freeze.groups import order_selection, validate_group_ids
from lake.freeze.measures import GroupMeasure
from lake.intake.observations import Observation, observation_signature


@dataclass(frozen=True)
class FrozenManifest:
    revision: int
    day_key: str
    edition: int
    group_ids: tuple[int, ...]

    def validate(self):
        code = 'BAD_MANIFEST'
        positive_id(self.revision, 'revision', code)
        positive_id(self.edition, 'edition', code)
        key(self.day_key, 'day key', code)
        if type(self.group_ids) is not tuple:
            raise LakeError(code, 'manifest groups require a tuple')
        validate_group_ids(self.group_ids, code)

    def to_data(self):
        return {
            'revision': self.revision,
            'day_key': self.day_key,
            'edition': self.edition,
            'group_ids': self.group_ids,
        }

    @classmethod
    def from_data(cls, data):
        code = 'BAD_MANIFEST'
        require_fields(data, ('revision', 'day_key', 'edition', 'group_ids'), code)
        result = cls(
            data['revision'], data['day_key'], data['edition'],
            sequence(data['group_ids'], 'manifest groups', code),
        )
        result.validate()
        return result


@dataclass(frozen=True)
class FrozenGroup:
    group_id: int
    observations: tuple[Observation, ...]
    measure: GroupMeasure

    def to_data(self):
        return {
            'group_id': self.group_id,
            'observations': observation_signature(self.observations),
            'measure': self.measure.to_data(),
        }

    @classmethod
    def from_data(cls, data):
        code = 'BAD_GROUP'
        require_fields(data, ('group_id', 'observations', 'measure'), code)
        return cls(
            positive_id(data['group_id'], 'group id', code),
            tuple(Observation.from_data(row) for row in sequence(data['observations'], 'observations', code)),
            GroupMeasure.from_data(data['measure']),
        )


def save_manifest(db, day_key, groups):
    edition, = db.execute(
        'SELECT COALESCE(MAX(edition), 0) + 1 FROM frozen_revisions WHERE day_key = ?', (day_key,)
    ).fetchone()
    revision = db.execute(
        'INSERT INTO frozen_revisions (day_key, edition) VALUES (?, ?)', (day_key, edition)
    ).lastrowid
    db.executemany(
        'INSERT INTO frozen_groups (revision, ordinal, group_id, body) VALUES (?, ?, ?, ?)',
        ((revision, ordinal, group.group_id, pack(group.to_data())) for ordinal, group in enumerate(groups)),
    )
    return FrozenManifest(revision, day_key, edition, tuple(group.group_id for group in groups))


def load_manifest(db, revision):
    positive_id(revision, 'revision', 'BAD_REVISION')
    header = db.execute(
        'SELECT day_key, edition FROM frozen_revisions WHERE revision = ?', (revision,)
    ).fetchone()
    if header is None:
        raise LakeError('UNKNOWN_REVISION', str(revision))
    directory = tuple(group_id for group_id, in db.execute(
        'SELECT group_id FROM frozen_groups WHERE revision = ? ORDER BY ordinal', (revision,)
    ))
    return FrozenManifest(revision, *header, directory)


def load_frozen_groups(db, revision, group_ids=None):
    manifest = load_manifest(db, revision)
    chosen = manifest.group_ids if group_ids is None else order_selection(
        manifest.group_ids, group_ids, 'BAD_SELECTION'
    )
    wanted = set(chosen)
    rows = db.execute(
        'SELECT group_id, body FROM frozen_groups WHERE revision = ? ORDER BY ordinal', (revision,)
    )
    return tuple(FrozenGroup.from_data(json.loads(body)) for group_id, body in rows if group_id in wanted)
