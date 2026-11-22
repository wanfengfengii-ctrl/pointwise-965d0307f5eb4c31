import json
from dataclasses import dataclass

from lake.db import LakeError, atomic, key, pack
from lake.intake.observations import Observation, observation_signature
from lake.intake.validation import validate_batch


@dataclass(frozen=True)
class StationBatch:
    day_key: str
    batch_id: str
    observations: tuple[Observation, ...]


def _find_batch(db, batch_id):
    row = db.execute(
        'SELECT day_key, observations FROM station_batches WHERE batch_id = ?', (batch_id,)
    ).fetchone()
    if row is None:
        return None
    day_key, payload = row
    observations = tuple(Observation.from_data(item) for item in json.loads(payload))
    return StationBatch(day_key, batch_id, observations)


def submit(db, day_key, batch_id, rows):
    observations = validate_batch(day_key, batch_id, rows)
    candidate = StationBatch(day_key, batch_id, observations)
    with atomic(db):
        existing = _find_batch(db, batch_id)
        if existing is not None:
            if existing != candidate:
                raise LakeError('BATCH_CONFLICT', batch_id)
            return existing
        db.execute(
            'INSERT INTO station_batches (batch_id, day_key, observations) VALUES (?, ?, ?)',
            (batch_id, day_key, pack(observation_signature(observations))),
        )
    return candidate


def load_batch(db, batch_id):
    key(batch_id, 'batch id', 'BAD_BATCH')
    batch = _find_batch(db, batch_id)
    if batch is None:
        raise LakeError('UNKNOWN_BATCH', batch_id)
    return batch
