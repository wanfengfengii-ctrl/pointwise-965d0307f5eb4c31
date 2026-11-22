from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from lake.db import connect_source, connect_warehouse
from lake.freeze.revisions import freeze
from lake.intake.batches import submit

DAY = '2026-06-18'
READINGS = ((1, 'north/01', 7), (3, 'south/01', 11))


class LakeTestCase(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.source_path = Path(temporary.name) / 'source.sqlite'
        self.warehouse_path = Path(temporary.name) / 'warehouse.sqlite'
        self.source = self.warehouse = None
        self.addCleanup(self.close_connections)
        self.open_source()
        self.open_warehouse()

    def close_source(self):
        if self.source is not None:
            self.source.close()
            self.source = None

    def close_warehouse(self):
        if self.warehouse is not None:
            self.warehouse.close()
            self.warehouse = None

    def close_connections(self):
        self.close_source()
        self.close_warehouse()

    def open_source(self):
        self.close_source()
        self.source = connect_source(self.source_path)

    def open_warehouse(self):
        self.close_warehouse()
        self.warehouse = connect_warehouse(self.warehouse_path)

    def make_day(self, batch_id='shift-a', rows=READINGS, group_ids=(1, 2, 3)):
        submit(self.source, DAY, batch_id, rows)
        result = freeze(self.source, DAY, (batch_id,), group_ids)
        return result.revision
