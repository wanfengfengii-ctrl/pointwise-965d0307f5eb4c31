import json

from lake.db import LakeError, atomic, key, pack, positive_id
from lake.dispatch.backlog import pending_groups
from lake.freeze.groups import order_selection


def _store_plan(db, revision, waves, replace):
    code = 'BAD_PLAN'
    if type(waves) is not dict or (not replace and not waves):
        raise LakeError(code, 'invalid mapping of wave names to groups')
    with atomic(db):
        pending = pending_groups(db, revision)
        normalized = {}
        for wave, groups in waves.items():
            key(wave, 'wave name', code)
            normalized[wave] = order_selection(pending, groups, code)
        if replace:
            db.execute('DELETE FROM delivery_waves WHERE revision = ?', (revision,))
        elif db.execute('SELECT 1 FROM delivery_waves WHERE revision = ?', (revision,)).fetchone():
            raise LakeError('PLAN_EXISTS', str(revision))
        db.executemany(
            'INSERT INTO delivery_waves (revision, wave, group_ids) VALUES (?, ?, ?)',
            ((revision, wave, pack(groups)) for wave, groups in normalized.items()),
        )
    return normalized


def plan_waves(db, revision, waves):
    return _store_plan(db, revision, waves, replace=False)


def replan(db, revision, waves):
    return _store_plan(db, revision, waves, replace=True)


def load_wave(db, revision, wave):
    positive_id(revision, 'revision', 'BAD_REVISION')
    key(wave, 'wave name', 'BAD_PLAN')
    row = db.execute(
        'SELECT group_ids FROM delivery_waves WHERE revision = ? AND wave = ?', (revision, wave)
    ).fetchone()
    if row is None:
        raise LakeError('UNKNOWN_WAVE', wave)
    return tuple(json.loads(row[0]))
