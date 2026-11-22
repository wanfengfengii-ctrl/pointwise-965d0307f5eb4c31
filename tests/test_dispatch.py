from dataclasses import replace

from lake.db import LakeError
from lake.dispatch.backlog import pending_groups
from lake.dispatch.confirmations import confirm
from lake.dispatch.coverage import confirmed_groups
from lake.dispatch.parcels import dispatch, load_parcel
from lake.dispatch.plans import load_wave, plan_waves, replan
from lake.receive.acceptance import accept
from lake.receive.receipts import Receipt, get_receipt
from tests import LakeTestCase


class DispatchTests(LakeTestCase):
    def test_sparse_receipt_after_replan(self):
        revision = self.make_day()
        plan_waves(self.source, revision, {'first': [1, 3]})
        old = dispatch(self.source, revision, 'old', wave='first')
        accept(self.warehouse, old)
        self.open_source()
        self.open_warehouse()
        self.assertEqual(pending_groups(self.source, revision), (1, 2, 3))
        self.assertEqual(replan(self.source, revision, {'next': [3, 2]}), {'next': (2, 3)})
        new = dispatch(self.source, revision, 'new', wave='next')
        old_receipt = get_receipt(self.warehouse, 'old')
        self.assertEqual(old_receipt, Receipt('old', revision, (1, 3)))
        self.assertEqual(confirm(self.source, old_receipt), (2,))
        self.assertEqual(confirm(self.source, old_receipt), (2,))
        self.open_source()
        self.assertEqual(pending_groups(self.source, revision), (2,))
        self.assertEqual(confirmed_groups(self.source, revision), frozenset({1, 3}))
        self.assertEqual(load_parcel(self.source, 'new'), new)
        self.assertEqual(confirm(self.source, accept(self.warehouse, new)), ())

    def test_replan_keeps_coverage(self):
        revision = self.make_day()
        plan_waves(self.source, revision, {'first': [1, 3], 'spare': [2]})
        old = dispatch(self.source, revision, 'old', wave='first')
        self.assertEqual(confirm(self.source, accept(self.warehouse, old)), (2,))
        self.assertEqual(replan(self.source, revision, {'fill': [2]}), {'fill': (2,)})
        self.open_source()
        self.assertEqual(pending_groups(self.source, revision), (2,))
        self.assertEqual(load_wave(self.source, revision, 'fill'), (2,))
        self.assertEqual(load_parcel(self.source, 'old'), old)
        with self.assertRaisesRegex(LakeError, 'UNKNOWN_WAVE'):
            load_wave(self.source, revision, 'first')
        with self.assertRaisesRegex(LakeError, 'BAD_PLAN'):
            replan(self.source, revision, {'illegal': [1]})
        self.assertEqual(load_wave(self.source, revision, 'fill'), (2,))
        self.assertEqual(replan(self.source, revision, {}), {})
        self.assertEqual(pending_groups(self.source, revision), (2,))

    def test_wrong_revision(self):
        first = self.make_day()
        second = self.make_day('shift-b')
        parcel = dispatch(self.source, first, 'first', group_ids=[1, 3])
        actual = accept(self.warehouse, parcel)
        for invalid, code in (
            (replace(actual, revision=second), 'BAD_RECEIPT'),
            (replace(actual, parcel_id='unknown'), 'UNKNOWN_PARCEL'),
            (replace(actual, group_ids=(1, 2, 3)), 'BAD_RECEIPT'),
            (replace(actual, group_ids=(True, 3)), 'BAD_RECEIPT'),
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(LakeError, code):
                    confirm(self.source, invalid)
                self.assertEqual(pending_groups(self.source, first), (1, 2, 3))
                self.assertEqual(pending_groups(self.source, second), (1, 2, 3))
        self.assertEqual(confirm(self.source, actual), (2,))
        self.assertEqual(pending_groups(self.source, second), (1, 2, 3))
