from lake.db import LakeError
from lake.intake.batches import load_batch, submit
from lake.intake.day_assembly import assemble_day
from tests import DAY, LakeTestCase


class IntakeTests(LakeTestCase):
    def test_conflicting_replay(self):
        original = submit(self.source, DAY, 'north', [(1, 'gate-a/01', 7)])
        with self.assertRaisesRegex(LakeError, 'BATCH_CONFLICT'):
            submit(self.source, DAY, 'north', [(1, 'gate-a/02', 8)])
        self.open_source()
        self.assertEqual(load_batch(self.source, 'north'), original)
        draft = assemble_day(self.source, DAY, ['north'])
        self.assertEqual([(row.source, row.liters) for row in draft.observations], [('gate-a/01', 7)])

    def test_same_batch(self):
        first = submit(self.source, DAY, 'north', [(1, 'gate-a/01', None), (1, 'gate-a/01', 0)])
        replay = submit(self.source, DAY, 'north', ((1, 'gate-a/01', None), (1, 'gate-a/01', 0)))
        self.assertEqual(first, replay)
        draft = assemble_day(self.source, DAY, ['north'])
        self.assertEqual([(row.position, row.liters) for row in draft.observations], [(1, None), (2, 0)])
        with self.assertRaisesRegex(LakeError, 'BATCH_CONFLICT'):
            submit(self.source, '2026-06-19', 'north', [(1, 'gate-a/01', None), (1, 'gate-a/01', 0)])

    def test_invalid_batch(self):
        for bad in (True, '8', 8.0):
            with self.subTest(reading=bad):
                with self.assertRaisesRegex(LakeError, 'BAD_BATCH'):
                    submit(self.source, DAY, 'bad', [(1, 'valid', 7), (2, 'invalid', bad)])
                with self.assertRaisesRegex(LakeError, 'UNKNOWN_BATCH'):
                    load_batch(self.source, 'bad')
        with self.assertRaisesRegex(LakeError, 'BAD_BATCH'):
            submit(self.source, DAY, 'bad', [(1, 'valid', 7), (True, '', 5)])
        accepted = submit(self.source, DAY, 'bad', [(1, 'valid', 7)])
        self.assertEqual(len(accepted.observations), 1)
