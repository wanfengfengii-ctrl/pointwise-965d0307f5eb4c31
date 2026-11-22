from lake.accounts.history import read
from lake.accounts.publication import PostResult, post
from lake.accounts.rollup import DayTotals
from lake.dispatch.backlog import pending_groups
from lake.dispatch.confirmations import confirm
from lake.dispatch.parcels import DeliveryParcel, dispatch
from lake.dispatch.plans import plan_waves, replan
from lake.receive.acceptance import accept
from lake.receive.receipts import get_receipt
from tests import LakeTestCase


class WorkflowTests(LakeTestCase):
    def test_shift_handoff(self):
        revision = self.make_day()
        plan_waves(self.source, revision, {'morning': (1, 3)})
        old_wire = dispatch(self.source, revision, 'morning', wave='morning').to_json()
        self.close_source()
        old = DeliveryParcel.from_json(old_wire)
        accept(self.warehouse, old)
        self.open_source()
        self.open_warehouse()
        replan(self.source, revision, {'evening': (2, 3)})
        supplement = dispatch(self.source, revision, 'evening', wave='evening')
        recovered = accept(self.warehouse, old)
        self.assertEqual(recovered, get_receipt(self.warehouse, 'morning'))
        source_missing = confirm(self.source, recovered)
        warehouse_missing = post(self.warehouse, revision)
        with self.subTest(stage='after the late receipt'):
            self.assertEqual(
                (source_missing, warehouse_missing), ((2,), PostResult(None, (2,))),
                'POINTWISE_SPARSE_OVERLAP late receipt must leave group 2 unconfirmed and unpublished',
            )
        self.close_source()
        second_receipt = accept(self.warehouse, supplement)
        self.assertEqual(second_receipt.group_ids, (2, 3))
        result = post(self.warehouse, revision)
        account = read(self.warehouse, result.account_id)
        with self.subTest(stage='after overlapping delivery'):
            self.assertEqual(account.totals, DayTotals(2, 18, 7, 11),
                             'POINTWISE_SPARSE_OVERLAP repeated group 3 must contribute once')
        self.assertEqual([(entry.group.group_id, entry.first_parcel_id) for entry in account.groups], [
            (1, 'morning'), (2, 'evening'), (3, 'morning'),
        ])
        self.open_source()
        self.open_warehouse()
        self.assertEqual(accept(self.warehouse, supplement), second_receipt)
        self.assertEqual(confirm(self.source, second_receipt), ())
        self.assertEqual(pending_groups(self.source, revision), ())
        self.assertEqual(post(self.warehouse, revision), result)
        self.assertEqual(read(self.warehouse, result.account_id), account)
