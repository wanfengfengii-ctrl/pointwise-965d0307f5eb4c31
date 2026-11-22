from dataclasses import dataclass

from lake.db import LakeError, decode_liters, encode_liters, key, positive_id, require_fields


@dataclass(frozen=True)
class Observation:
    group_id: int
    source: str
    liters: int | None
    batch_id: str
    position: int

    def validate(self):
        code = 'BAD_OBSERVATION'
        positive_id(self.group_id, 'group id', code)
        positive_id(self.position, 'batch position', code)
        key(self.source, 'source', code)
        key(self.batch_id, 'batch id', code)
        if self.liters is not None and type(self.liters) is not int:
            raise LakeError(code, 'a reading requires integer liters or None')

    def to_data(self):
        return {
            'group_id': self.group_id,
            'source': self.source,
            'liters': encode_liters(self.liters),
            'batch_id': self.batch_id,
            'position': self.position,
        }

    @classmethod
    def from_data(cls, data):
        code = 'BAD_OBSERVATION'
        require_fields(data, ('group_id', 'source', 'liters', 'batch_id', 'position'), code)
        result = cls(
            data['group_id'], data['source'], decode_liters(data['liters'], code),
            data['batch_id'], data['position'],
        )
        result.validate()
        return result


def observation_signature(observations):
    return tuple(observation.to_data() for observation in observations)
