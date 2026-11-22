from dataclasses import replace

from lake.accounts.history import read
from lake.accounts.publication import post
from lake.accounts.readiness import assess_readiness
from lake.accounts.rollup import DayTotals
from lake.db import LakeError, initialize_source, initialize_warehouse
from lake.dispatch.backlog import pending_groups
from lake.dispatch.confirmations import confirm
from lake.dispatch.parcels import DeliveryParcel, dispatch, load_parcel
from lake.dispatch.plans import plan_waves, replan
from lake.freeze.manifest import load_manifest
from lake.intake.batches import load_batch
from lake.receive.acceptance import accept
from lake.receive.catalog import load_catalog
from lake.receive.group_ledger import find_group, list_received_groups
from lake.receive.parcel_log import load_accepted_parcel
from lake.receive.receipts import Receipt, get_receipt
from tests import DAY, LakeTestCase


class ExchangeTests(LakeTestCase):
    def test_offline_receive(self):
        revision = self.make_day()
        parcel = dispatch(self.source, revision, 'ordinary', group_ids=[1, 2])
        wire = parcel.to_json()
        self.close_source()
        self.assertEqual(accept(self.warehouse, DeliveryParcel.from_json(wire)), Receipt('ordinary', revision, (1, 2)))
        self.assertEqual(assess_readiness(self.warehouse, revision).missing_groups, (3,))

    def test_full_manifest(self):
        revision = self.make_day()
        parcel = dispatch(self.source, revision, 'sparse', group_ids=[3, 1])
        self.close_source()
        receipt = accept(self.warehouse, parcel)
        self.assertEqual(load_catalog(self.warehouse, revision).group_ids, (1, 2, 3))
        self.assertEqual(receipt.group_ids, (1, 3))
        self.assertEqual([entry.group.group_id for entry in list_received_groups(self.warehouse, revision)], [1, 3])
        self.assertEqual(assess_readiness(self.warehouse, revision).missing_groups, (2,))

    def test_parcel_replay(self):
        revision = self.make_day()
        plan_waves(self.source, revision, {'first': [3, 1]})
        original = dispatch(self.source, revision, 'east', wave='first')
        self.assertEqual(original.group_ids, (1, 3))
        with self.assertRaisesRegex(LakeError, 'BAD_SELECTION'):
            dispatch(self.source, revision, 'invalid', group_ids=[1, 99])
        with self.assertRaisesRegex(LakeError, 'UNKNOWN_PARCEL'):
            load_parcel(self.source, 'invalid')
        replan(self.source, revision, {'first': [2, 3]})
        self.open_source()
        self.assertEqual(load_parcel(self.source, 'east'), original)
        self.assertEqual(dispatch(self.source, revision, 'east', group_ids=[1, 3]), original)
        with self.assertRaisesRegex(LakeError, 'PARCEL_CONFLICT'):
            dispatch(self.source, revision, 'east', wave='first')
        self.assertEqual(load_parcel(self.source, 'east'), original)
        accept(self.warehouse, original)
        other_body = replace(original, groups=original.groups[:1])
        with self.assertRaisesRegex(LakeError, 'PARCEL_CONFLICT'):
            accept(self.warehouse, other_body)
        self.assertEqual(get_receipt(self.warehouse, 'east').group_ids, (1, 3))

    def test_overlap(self):
        revision = self.make_day()
        old = dispatch(self.source, revision, 'old', group_ids=[1, 3])
        new = dispatch(self.source, revision, 'new', group_ids=[2, 3])
        self.close_source()
        accept(self.warehouse, old)
        self.assertEqual(post(self.warehouse, revision).missing_groups, (2,))
        first_third_group = find_group(self.warehouse, revision, 3)
        accept(self.warehouse, new)
        groups = list_received_groups(self.warehouse, revision)
        self.assertEqual([entry.group.group_id for entry in groups], [1, 2, 3])
        self.assertEqual(find_group(self.warehouse, revision, 3), first_third_group)
        account_id = post(self.warehouse, revision).account_id
        account = read(self.warehouse, account_id)
        self.assertEqual(account.totals, DayTotals(2, 18, 7, 11))
        self.assertEqual([entry.first_parcel_id for entry in account.groups], ['old', 'new', 'old'])

    def test_overlap_receipt(self):
        revision = self.make_day()
        old = dispatch(self.source, revision, 'old', group_ids=[1, 3])
        new = dispatch(self.source, revision, 'new', group_ids=[2, 3])
        accept(self.warehouse, old)
        before = list_received_groups(self.warehouse, revision)
        new_receipt = accept(self.warehouse, new)
        self.assertEqual(new_receipt, Receipt('new', revision, (2, 3)))
        after = list_received_groups(self.warehouse, revision)
        self.assertEqual([item for item in after if item not in before], [find_group(self.warehouse, revision, 2)])
        self.assertEqual(confirm(self.source, new_receipt), (1,))
        self.open_warehouse()
        self.assertEqual(accept(self.warehouse, new), new_receipt)
        self.assertEqual(get_receipt(self.warehouse, 'old'), Receipt('old', revision, (1, 3)))
        self.assertEqual(list_received_groups(self.warehouse, revision), after)

    def test_conflicting_group_is_atomic(self):
        revision = self.make_day()
        old = dispatch(self.source, revision, 'old', group_ids=[1, 3])
        new = dispatch(self.source, revision, 'new', group_ids=[2, 3])
        accept(self.warehouse, old)
        empty, third = new.groups
        shifted = replace(third.observations[0], source='other-gate')
        incompatible = replace(new, groups=(empty, replace(third, observations=(shifted,))))
        with self.assertRaisesRegex(LakeError, 'GROUP_CONFLICT'):
            accept(self.warehouse, incompatible)
        self.open_warehouse()
        self.assertIsNone(find_group(self.warehouse, revision, 2))
        self.assertEqual(find_group(self.warehouse, revision, 3).group, third)
        self.assertIsNone(load_accepted_parcel(self.warehouse, 'new'))
        with self.assertRaisesRegex(LakeError, 'UNKNOWN_RECEIPT'):
            get_receipt(self.warehouse, 'new')
        self.assertEqual(post(self.warehouse, revision).missing_groups, (2,))
        self.assertEqual(accept(self.warehouse, new), Receipt('new', revision, (2, 3)))

    def test_rejects_conflicting_catalog_and_invalid_measure(self):
        revision = self.make_day()
        old = dispatch(self.source, revision, 'old', group_ids=[1])
        new = dispatch(self.source, revision, 'new', group_ids=[3])
        third, = new.groups
        bogus_measure = replace(third.measure, total_liters=12)
        with self.assertRaisesRegex(LakeError, 'MEASURE_MISMATCH'):
            accept(self.warehouse, replace(new, groups=(replace(third, measure=bogus_measure),)))
        self.assertIsNone(load_catalog(self.warehouse, revision))
        accept(self.warehouse, old)
        altered = replace(new.manifest, group_ids=(1, 3))
        with self.assertRaisesRegex(LakeError, 'CATALOG_CONFLICT'):
            accept(self.warehouse, replace(new, manifest=altered))
        self.assertIsNone(load_accepted_parcel(self.warehouse, 'new'))
        self.assertEqual(post(self.warehouse, revision).missing_groups, (2, 3))

    def test_reinitialize(self):
        revision = self.make_day('customer-batch', [(4, 'customer-gate', 31)], [4, 9])
        parcel = dispatch(self.source, revision, 'customer-parcel', group_ids=[4])
        receipt = accept(self.warehouse, parcel)
        self.assertEqual(confirm(self.source, receipt), (9,))
        for _ in range(2):
            initialize_source(self.source)
            initialize_warehouse(self.warehouse)
        self.assertEqual(load_batch(self.source, 'customer-batch').day_key, DAY)
        self.assertEqual(load_manifest(self.source, revision).group_ids, (4, 9))
        self.assertEqual(load_parcel(self.source, 'customer-parcel'), parcel)
        self.assertEqual(get_receipt(self.warehouse, 'customer-parcel'), receipt)
        self.assertEqual(pending_groups(self.source, revision), (9,))
        last = dispatch(self.source, revision, 'customer-fill', group_ids=[9])
        self.assertEqual(confirm(self.source, accept(self.warehouse, last)), ())
        account = read(self.warehouse, post(self.warehouse, revision).account_id)
        self.assertEqual(account.totals, DayTotals(1, 31, 31, 31))
