from dataclasses import dataclass

from lake.db import LakeError, key, sequence
from lake.intake.batches import load_batch
from lake.intake.observations import Observation


@dataclass(frozen=True)
class DayDraft:
    day_key: str
    batch_ids: tuple[str, ...]
    observations: tuple[Observation, ...]


def assemble_day(db, day_key, batch_ids):
    code = 'BAD_DRAFT'
    key(day_key, 'day key', code)
    ordered_batches = sequence(batch_ids, 'batch ids', code)
    seen = set()
    observations = []
    for batch_id in ordered_batches:
        key(batch_id, 'batch id', code)
        if batch_id in seen:
            raise LakeError(code, f'duplicate batch {batch_id}')
        seen.add(batch_id)
        batch = load_batch(db, batch_id)
        if batch.day_key != day_key:
            raise LakeError('WRONG_BATCH_DAY', batch_id)
        observations.extend(batch.observations)
    return DayDraft(day_key, ordered_batches, tuple(observations))
