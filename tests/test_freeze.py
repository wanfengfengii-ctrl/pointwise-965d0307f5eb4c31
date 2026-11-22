from lake.db import LakeError
from lake.freeze.manifest import load_frozen_groups, load_manifest
from lake.freeze.measures import GroupMeasure
from lake.freeze.revisions import freeze
from lake.intake.batches import submit
from tests import DAY, LakeTestCase


class FrozenDayTests(LakeTestCase):
    def test_groups(self):
        revision = self.make_day()
        self.assertEqual(load_manifest(self.source, revision).group_ids, (1, 2, 3))
        groups = load_frozen_groups(self.source, revision)
        self.assertEqual(tuple(group.group_id for group in groups), (1, 2, 3))
        self.assertEqual(tuple(group.measure for group in groups), (
            GroupMeasure(1, 7, 7, 7), GroupMeasure(0, 0, None, None), GroupMeasure(1, 11, 11, 11),
        ))
        self.assertEqual(groups[1].observations, ())

    def test_ordered_sources(self):
        submit(self.source, DAY, 'a', [(5, 'a/03', 3), (5, 'a/01', None)])
        submit(self.source, DAY, 'z', [(2, 'z/04', 6), (5, 'z/02', 9), (5, 'z/01', 4)])
        manifest = freeze(self.source, DAY, ['z', 'a'], [5, 9, 2])
        self.assertEqual(manifest.group_ids, (5, 9, 2))
        group, = load_frozen_groups(self.source, manifest.revision, [5])
        self.assertEqual([(row.batch_id, row.position, row.source, row.liters) for row in group.observations], [
            ('z', 2, 'z/02', 9), ('z', 3, 'z/01', 4), ('a', 1, 'a/03', 3), ('a', 2, 'a/01', None),
        ])

    def test_invalid_freeze(self):
        first = self.make_day()
        submit(self.source, '2026-06-19', 'wrong-day', [(1, 'other', 5)])
        cases = (
            (['unknown'], [1], 'UNKNOWN_BATCH'),
            (['wrong-day'], [1], 'WRONG_BATCH_DAY'),
            (['shift-a', 'shift-a'], [1, 3], 'BAD_DRAFT'),
            (['shift-a'], [1, 1, 3], 'BAD_DIRECTORY'),
            (['shift-a'], [1], 'UNDECLARED_GROUP'),
            ([], [], 'BAD_DIRECTORY'),
        )
        for batches, groups, code in cases:
            with self.subTest(code=code):
                with self.assertRaisesRegex(LakeError, code):
                    freeze(self.source, DAY, batches, groups)
        self.assertEqual(load_manifest(self.source, first).group_ids, (1, 2, 3))
        successor = freeze(self.source, DAY, ['shift-a'], [1, 3])
        self.assertEqual((successor.revision, successor.edition), (first + 1, 2))

    def test_append_revision(self):
        first = self.make_day()
        original_groups = load_frozen_groups(self.source, first)
        second = self.make_day('shift-b', [(4, 'new/01', 4), (1, 'new/02', 15)], [4, 1])
        self.open_source()
        self.assertEqual(load_manifest(self.source, first).edition, 1)
        self.assertEqual(load_manifest(self.source, second).edition, 2)
        self.assertEqual(load_frozen_groups(self.source, first), original_groups)
        self.assertEqual([group.measure.total_liters for group in load_frozen_groups(self.source, second)], [4, 15])

    def test_integer_measures(self):
        revision = self.make_day('units', [
            (1, 'a', 7), (1, 'b', None), (2, 'c', 0), (3, 'd', None),
            (4, 'e', 2**63 - 1), (4, 'f', 2**63 - 1),
        ], [1, 2, 3, 4])
        self.open_source()
        groups = load_frozen_groups(self.source, revision)
        self.assertEqual([group.measure for group in groups], [
            GroupMeasure(1, 7, 7, 7),
            GroupMeasure(1, 0, 0, 0),
            GroupMeasure(0, 0, None, None),
            GroupMeasure(2, 18446744073709551614, 9223372036854775807, 9223372036854775807),
        ])
        self.assertEqual([row.liters for row in groups[0].observations], [7, None])
        self.assertEqual([row.source for row in groups[2].observations], ['d'])
