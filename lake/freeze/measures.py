from dataclasses import dataclass

from lake.db import LakeError, decode_liters, encode_liters, require_fields


@dataclass(frozen=True)
class GroupMeasure:
    count: int
    total_liters: int
    minimum_liters: int | None
    maximum_liters: int | None

    def validate(self):
        code = 'BAD_MEASURE'
        if type(self.count) is not int or self.count < 0 or type(self.total_liters) is not int:
            raise LakeError(code, 'invalid count or total')
        low, high = self.minimum_liters, self.maximum_liters
        if self.count == 0:
            if self.total_liters != 0 or low is not None or high is not None:
                raise LakeError(code, 'empty measure requires zero total and null extrema')
        elif type(low) is not int or type(high) is not int or low > high:
            raise LakeError(code, 'invalid extrema')

    def to_data(self):
        return {
            'count': self.count,
            'total_liters': encode_liters(self.total_liters),
            'minimum_liters': encode_liters(self.minimum_liters),
            'maximum_liters': encode_liters(self.maximum_liters),
        }

    @classmethod
    def from_data(cls, data):
        code = 'BAD_MEASURE'
        require_fields(data, ('count', 'total_liters', 'minimum_liters', 'maximum_liters'), code)
        result = cls(
            data['count'], decode_liters(data['total_liters'], code),
            decode_liters(data['minimum_liters'], code), decode_liters(data['maximum_liters'], code),
        )
        result.validate()
        return result


def measure_group(observations):
    values = [observation.liters for observation in observations if observation.liters is not None]
    return GroupMeasure(len(values), sum(values), min(values, default=None), max(values, default=None))
