from lake.db import LakeError, key, sequence
from lake.intake.observations import Observation


def validate_batch(day_key, batch_id, rows):
    code = 'BAD_BATCH'
    key(day_key, 'day key', code)
    key(batch_id, 'batch id', code)
    observations = []
    for position, row in enumerate(sequence(rows, 'rows', code), start=1):
        fields = sequence(row, f'row {position}', code)
        if len(fields) != 3:
            raise LakeError(code, f'row {position} requires group, source and liters')
        observation = Observation(*fields, batch_id, position)
        try:
            observation.validate()
        except LakeError as exc:
            raise LakeError(code, f'row {position}: {exc}') from exc
        observations.append(observation)
    return tuple(observations)
