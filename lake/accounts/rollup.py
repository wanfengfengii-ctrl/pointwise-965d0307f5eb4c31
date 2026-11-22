from dataclasses import dataclass

from lake.freeze.measures import GroupMeasure
from lake.receive.group_ledger import ReceivedGroup


@dataclass(frozen=True)
class DayTotals(GroupMeasure):
    pass


def rollup_groups(groups: tuple[ReceivedGroup, ...]):
    measures = [entry.group.measure for entry in groups]
    effective = [measure for measure in measures if measure.count]
    return DayTotals(
        sum(measure.count for measure in measures),
        sum(measure.total_liters for measure in measures),
        min((measure.minimum_liters for measure in effective), default=None),
        max((measure.maximum_liters for measure in effective), default=None),
    )
