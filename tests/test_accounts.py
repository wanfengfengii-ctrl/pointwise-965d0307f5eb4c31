from lake.accounts.history import read
from lake.accounts.publication import PostResult, post
from lake.accounts.rollup import DayTotals
from lake.accounts.snapshots import load_by_revision
from lake.db import LakeError, initialize_warehouse
from lake.dispatch.parcels import dispatch
from lake.receive.acceptance import accept
from tests import LakeTestCase


class AccountTests(LakeTestCase):
    def receive(self, revision, parcel_id, groups):
        parcel = dispatch(self.source, revision, parcel_id, group_ids=groups)
        return accept(self.warehouse, parcel)

    def test_missing_empty_group(self):
        revision = self.make_day()
        self.receive(revision, 'early', [1, 3])
        self.assertEqual(post(self.warehouse, revision), PostResult(None, (2,)))
        self.assertIsNone(load_by_revision(self.warehouse, revision))
        self.receive(revision, 'empty', [2])
        result = post(self.warehouse, revision)
        self.assertEqual(result.missing_groups, ())
        account = read(self.warehouse, result.account_id)
        self.assertEqual(account.totals, DayTotals(2, 18, 7, 11))
        self.assertEqual([entry.group.group_id for entry in account.groups], [1, 2, 3])

    def test_extrema_order(self):
        revision = self.make_day('extrema', [(1, 'a', 7), (3, 'b', 11), (4, 'c', 5)], [1, 2, 3, 4])
        self.receive(revision, 'late-groups-first', [4, 2])
        self.receive(revision, 'remaining', [3, 1])
        account = read(self.warehouse, post(self.warehouse, revision).account_id)
        self.assertEqual(account.totals, DayTotals(3, 23, 5, 11))
        self.assertEqual([entry.group.group_id for entry in account.groups], [1, 2, 3, 4])

    def test_all_empty(self):
        revision = self.make_day('empty', [(4, 'offline-sensor', None)], [9, 4])
        self.receive(revision, 'explicit-missing', [4])
        self.assertEqual(post(self.warehouse, revision), PostResult(None, (9,)))
        self.receive(revision, 'empty-group', [9])
        result = post(self.warehouse, revision)
        account = read(self.warehouse, result.account_id)
        self.assertEqual(account.totals, DayTotals(0, 0, None, None))
        self.assertEqual([entry.group.group_id for entry in account.groups], [9, 4])
        self.assertEqual(account.groups[1].group.observations[0].source, 'offline-sensor')

    def test_history_after_revision(self):
        first = self.make_day()
        self.receive(first, 'first', [1, 2, 3])
        old_number = post(self.warehouse, first).account_id
        original = read(self.warehouse, old_number)
        self.make_day('updated', [(7, 'revised-site', 35)], [7])
        self.open_warehouse()
        self.assertEqual(read(self.warehouse, old_number), original)
        self.assertEqual(original.totals, DayTotals(2, 18, 7, 11))
        self.assertEqual([entry.first_parcel_id for entry in original.groups], ['first', 'first', 'first'])
        self.assertEqual(original.groups[0].group.observations[0].source, 'north/01')

    def test_separate_snapshot(self):
        first = self.make_day()
        self.receive(first, 'old', [1, 2, 3])
        first_result = post(self.warehouse, first)
        old_account = read(self.warehouse, first_result.account_id)
        second = self.make_day('corrected', [(3, 'new/south', 10), (1, 'new/north', 13)], [3, 2, 1])
        with self.assertRaisesRegex(LakeError, 'UNKNOWN_REVISION'):
            post(self.warehouse, second)
        self.receive(second, 'new', [1, 2, 3])
        second_result = post(self.warehouse, second)
        self.assertNotEqual(first_result.account_id, second_result.account_id)
        self.open_warehouse()
        for _ in range(2):
            initialize_warehouse(self.warehouse)
        old = read(self.warehouse, first_result.account_id)
        new = read(self.warehouse, second_result.account_id)
        self.assertEqual(old, old_account)
        self.assertEqual((old.revision, old.edition, old.totals), (first, 1, DayTotals(2, 18, 7, 11)))
        self.assertEqual((new.revision, new.edition, new.totals), (second, 2, DayTotals(2, 23, 10, 13)))
        self.assertEqual([entry.group.group_id for entry in old.groups], [1, 2, 3])
        self.assertEqual([entry.group.group_id for entry in new.groups], [3, 2, 1])
        self.assertEqual(new.groups[0].group.observations[0].source, 'new/south')
        self.assertEqual(old.groups[0].group.observations[0].source, 'north/01')
        self.assertEqual(post(self.warehouse, first), first_result)

    def test_unknown_account(self):
        self.assertIsNone(read(self.warehouse, 'DW-999999'))

    def test_exact_day_total_beyond_sqlite_integer(self):
        revision = self.make_day('large', [(1, 'a', 2**63), (2, 'b', 2**63)], [2, 1])
        self.receive(revision, 'large', [1, 2])
        number = post(self.warehouse, revision).account_id
        self.open_warehouse()
        self.assertEqual(read(self.warehouse, number).totals, DayTotals(2, 18446744073709551616, 2**63, 2**63))
