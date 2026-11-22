import json
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from lake.accounts.history import export_audit, read, verify_audit
from lake.accounts.publication import PostResult, post
from lake.accounts.rollup import DayTotals
from lake.audit import redact_anchor
from lake.db import LakeError, connect_warehouse, pack
from lake.dispatch.confirmations import confirm
from lake.dispatch.parcels import DeliveryParcel, dispatch, load_parcel
from lake.freeze.anchor import normalize_anchor
from lake.freeze.manifest import load_manifest
from lake.freeze.measures import GroupMeasure
from lake.freeze.revisions import freeze
from lake.intake.batches import submit
from lake.receive.acceptance import accept
from lake.receive.receipts import get_receipt
from tests import DAY, LakeTestCase


OLD_ORDER = (5, 9, 12)
NEW_ORDER = (9, 5, 12)
OLD_BATCH = 'audit-morning'
NEW_BATCH = 'audit-afternoon'
OLD_ROWS = ((5, 'gate/a', 7), (9, 'gate/b-old', 7))
NEW_ROWS = ((5, 'gate/a', 7), (9, 'gate/b-new', 7))


def detached(value):
    return json.loads(pack(value))


def substitute_source(wire, source):
    data = json.loads(wire)
    data['groups'][0]['observations'][0]['source'] = source
    return pack(data)


class AuditV2Tests(LakeTestCase):
    def stage(self):
        submit(self.source, DAY, OLD_BATCH, OLD_ROWS)
        submit(self.source, DAY, NEW_BATCH, NEW_ROWS)
        old, old_anchor = freeze(self.source, DAY, (OLD_BATCH,), OLD_ORDER, with_anchor=True)
        new, new_anchor = freeze(self.source, DAY, (NEW_BATCH,), NEW_ORDER, with_anchor=True)
        return old, detached(old_anchor), new, detached(new_anchor)

    def issue(self, revision, parcel_id, groups):
        return dispatch(self.source, revision, parcel_id, group_ids=groups)

    def accept(self, parcel, anchor):
        return accept(self.warehouse, parcel, anchor=anchor)

    def test_freeze_returns_anchor_and_keeps_v1_api(self):
        submit(self.source, DAY, 'plain', ((1, 'north/01', 7),))
        manifest = freeze(self.source, DAY, ('plain',), (1,))
        self.assertEqual(load_manifest(self.source, manifest.revision), manifest)
        anchored, anchor = freeze(self.source, DAY, ('plain',), (1,), with_anchor=True)
        self.assertEqual(detached(anchor), normalize_anchor(anchor))
        self.assertIs(type(anchor['revision']), int)
        self.assertEqual(tuple(anchor['group_ids']), (1,))
        self.assertEqual(len(anchor['measure_commitments']['1']), 64)
        # The anchor says nothing about the reading or the full-day total.
        text = pack(anchor)
        for secret in ('north/01', 'liters', 'observations', 'total_liters', 'batch_id'):
            self.assertNotIn(secret, text)

    def test_first_tampered_parcel_is_rejected_atomically(self):
        old, anchor, new, _ = self.stage()
        original = self.issue(old.revision, 'first', (9,))
        changed = DeliveryParcel.from_json(substitute_source(original.to_json(), 'gate/substituted'))
        with self.assertRaisesRegex(LakeError, 'EVIDENCE_MISMATCH'):
            self.accept(changed, anchor)
        with self.assertRaisesRegex(LakeError, 'UNKNOWN_RECEIPT'):
            get_receipt(self.warehouse, 'first')
        with self.assertRaisesRegex(LakeError, 'UNKNOWN_REVISION'):
            post(self.warehouse, old.revision)
        receipt = self.accept(original, anchor)
        self.assertEqual(receipt.group_ids, (9,))
        self.assertEqual(confirm(self.source, receipt), (5, 12))
        self.assertEqual(post(self.warehouse, old.revision), PostResult(None, (5, 12)))

    def test_anchor_is_mandatory_and_bound_to_the_edition(self):
        old, anchor, new, new_anchor = self.stage()
        parcel = self.issue(old.revision, 'first', (9,))
        with self.assertRaisesRegex(LakeError, 'MISSING_ANCHOR'):
            accept(self.warehouse, parcel)
        with self.assertRaisesRegex(LakeError, 'PARCEL_ANCHOR_MISMATCH'):
            self.accept(parcel, {**anchor, 'revision': parcel.manifest.revision + 99})
        with self.assertRaisesRegex(LakeError, 'PARCEL_ANCHOR_MISMATCH'):
            self.accept(parcel, new_anchor)
        self.accept(original := parcel, anchor)
        with self.assertRaisesRegex(LakeError, 'MISSING_ANCHOR'):
            accept(self.warehouse, original)
        replayed = DeliveryParcel.from_json(original.to_json())
        self.assertEqual(self.accept(replayed, detached(anchor)), get_receipt(self.warehouse, 'first'))

    def test_v1_material_cannot_join_a_v2_edition(self):
        old, anchor, _, _ = self.stage()
        parcel = self.issue(old.revision, 'first', (9,))
        self.accept(parcel, anchor)
        legacy = pack({
            'parcel_id': 'legacy',
            'manifest': parcel.manifest.to_data(),
            'groups': [group.to_data() for group in parcel.groups],
        })
        with self.assertRaisesRegex(LakeError, 'MODE_CONFLICT'):
            accept(self.warehouse, DeliveryParcel.from_json(legacy), anchor=anchor)
        with self.assertRaisesRegex(LakeError, 'MODE_CONFLICT'):
            accept(self.warehouse, DeliveryParcel.from_json(legacy), anchor=anchor)
        with TemporaryDirectory() as directory:
            with closing(connect_warehouse(Path(directory) / 'fresh.sqlite')) as fresh:
                with self.assertRaisesRegex(LakeError, 'UNEXPECTED_ANCHOR'):
                    accept(fresh, DeliveryParcel.from_json(legacy), anchor=anchor)

    def test_complete_day_and_alt_edition(self):
        old, anchor, new, new_anchor = self.stage()
        self.accept(self.issue(old.revision, 'first', (9,)), anchor)
        self.accept(self.issue(old.revision, 'rest', (5, 12)), anchor)
        result = post(self.warehouse, old.revision)
        account = read(self.warehouse, result.account_id)
        self.assertEqual(account.totals, DayTotals(2, 14, 7, 7))
        self.accept(self.issue(new.revision, 'moved', NEW_ORDER), new_anchor)
        newer = post(self.warehouse, new.revision)
        self.assertNotEqual(newer.account_id, result.account_id)
        moved = read(self.warehouse, newer.account_id)
        self.assertEqual([entry.group.group_id for entry in moved.groups], list(NEW_ORDER))
        self.assertEqual(moved.groups[0].group.observations[0].source, 'gate/b-new')
        self.assertEqual(moved.totals, DayTotals(2, 14, 7, 7))

    def test_export_and_detached_verification(self):
        old, anchor, new, _ = self.stage()
        self.accept(self.issue(old.revision, 'first', (9,)), anchor)
        self.accept(self.issue(old.revision, 'rest', (5, 12)), anchor)
        number = post(self.warehouse, old.revision).account_id
        self.close_source()
        self.open_warehouse()
        measure_bundle = export_audit(self.warehouse, number, [9])
        detail_bundle = export_audit(self.warehouse, number, (9,), detail=True)
        empty_bundle = export_audit(self.warehouse, number, [12])
        self.close_warehouse()
        self.assertEqual(
            verify_audit(detached(measure_bundle), detached(anchor), [9]),
            [{'ordinal': 2, 'group_id': 9,
              'measure': GroupMeasure(1, 7, 7, 7).to_data()}],
        )
        detail = verify_audit(detached(detail_bundle), detached(anchor), (9,), detail=True)
        self.assertEqual(detail[0]['ordinal'], 2)
        self.assertEqual(detail[0]['observations'], [{
            'group_id': 9, 'source': 'gate/b-old', 'liters': '7',
            'batch_id': OLD_BATCH, 'position': 2,
        }])
        self.assertEqual(
            verify_audit(empty_bundle, anchor, [12]),
            [{'ordinal': 3, 'group_id': 12, 'measure': GroupMeasure(0, 0, None, None).to_data()}],
        )

    def test_bundles_do_not_expose_hidden_material(self):
        old, anchor, new, _ = self.stage()
        self.accept(self.issue(old.revision, 'first', (9,)), anchor)
        self.accept(self.issue(old.revision, 'rest', (5, 12)), anchor)
        number = post(self.warehouse, old.revision).account_id
        detail_text = pack(export_audit(self.warehouse, number, [9], detail=True))
        self.assertIn('gate/b-old', detail_text)
        self.assertNotIn('gate/a', detail_text)
        self.assertNotIn('gate/b-new', detail_text)
        self.assertNotIn('totals', detail_text)
        measure_text = pack(export_audit(self.warehouse, number, [9]))
        self.assertNotIn('observations', measure_text)
        self.assertNotIn('audit-morning', measure_text)

    def test_wrong_scope_granularity_and_position_are_rejected(self):
        old, anchor, new, new_anchor = self.stage()
        self.accept(self.issue(old.revision, 'first', (9,)), anchor)
        self.accept(self.issue(old.revision, 'rest', (5, 12)), anchor)
        number = post(self.warehouse, old.revision).account_id
        detail_bundle = export_audit(self.warehouse, number, [9], detail=True)
        measure_bundle = export_audit(self.warehouse, number, [9])

        def rejected(bundle, trusted, groups, detail=False, *_, code=''):
            with self.assertRaises((LakeError, ValueError)) as caught:
                verify_audit(bundle, trusted, groups, detail=detail)
            if code:
                self.assertEqual(getattr(caught.exception, 'code', ''), code)

        rejected(detail_bundle, new_anchor, [9], True)
        rejected(detail_bundle, anchor, [5], True, code='WRONG_SCOPE')
        rejected(detail_bundle, anchor, [9, 12], True, code='WRONG_SCOPE')
        rejected(detail_bundle, anchor, [9], False, code='WRONG_DETAIL')
        rejected(measure_bundle, anchor, [9], True, code='WRONG_DETAIL')
        swapped = json.loads(pack(detail_bundle))
        swapped['groups'][0]['ordinal'] = 1
        rejected(swapped, anchor, [9], True, code='WRONG_POSITION')
        relabelled = json.loads(pack(detail_bundle))
        relabelled['groups'][0]['group_id'] = 5
        rejected(relabelled, anchor, [9], True)
        altered = json.loads(pack(detail_bundle))
        altered['groups'][0]['observations'][0]['liters'] = '8'
        rejected(altered, anchor, [9], True, code='MEASURE_MISMATCH')
        text_swap = json.loads(pack(detail_bundle))
        text_swap['groups'][0]['observations'][0]['source'] = 'gate/substituted'
        rejected(text_swap, anchor, [9], True, code='EVIDENCE_MISMATCH')

    def test_cross_version_splice_is_rejected(self):
        old, anchor, new, new_anchor = self.stage()
        old_first = self.issue(old.revision, 'first', (9,))
        new_moved = self.issue(new.revision, 'moved', (9,))
        spliced = replace(
            old_first,
            manifest=new_moved.manifest,
            groups=new_moved.groups,
            anchor=new_moved.anchor,
            evidence=new_moved.evidence,
        )
        with self.assertRaisesRegex(LakeError, 'PARCEL_ANCHOR_MISMATCH'):
            self.accept(spliced, anchor)
        with self.assertRaisesRegex(LakeError, 'PARCEL_ANCHOR_MISMATCH'):
            self.accept(old_first, new_anchor)
        with self.assertRaisesRegex(LakeError, 'UNKNOWN_RECEIPT'):
            get_receipt(self.warehouse, 'first')

    def test_selection_and_legacy_accounts(self):
        old, anchor, new, new_anchor = self.stage()
        self.accept(self.issue(old.revision, 'first', (9,)), anchor)
        self.accept(self.issue(old.revision, 'rest', (5, 12)), anchor)
        number = post(self.warehouse, old.revision).account_id
        for groups, code in (([], 'BAD_SELECTION'), ([9, 9], 'BAD_SELECTION'),
                             ([9, 77], 'BAD_SELECTION'), ('9', 'BAD_SELECTION')):
            with self.subTest(groups=groups):
                with self.assertRaisesRegex(LakeError, code):
                    export_audit(self.warehouse, number, groups)
        with self.assertRaisesRegex(LakeError, 'UNKNOWN_ACCOUNT'):
            export_audit(self.warehouse, 'DW-999999', [9])

        # A plain V1 edition still posts normally but offers no V2 audit material.
        submit(self.source, DAY, 'v1-batch', [(1, 'plain/01', 4)])
        v1 = freeze(self.source, DAY, ('v1-batch',), (1,))
        accept(self.warehouse, dispatch(self.source, v1.revision, 'v1-parcel', group_ids=(1,)))
        v1_number = post(self.warehouse, v1.revision).account_id
        self.assertEqual(read(self.warehouse, v1_number).totals, DayTotals(1, 4, 4, 4))
        with self.assertRaisesRegex(LakeError, 'NO_AUDIT_BASIS'):
            export_audit(self.warehouse, v1_number, [1])

    def test_same_value_group_material_cannot_stand_in(self):
        old, anchor, new, new_anchor = self.stage()
        self.accept(self.issue(old.revision, 'first', (9,)), anchor)
        self.accept(self.issue(old.revision, 'rest', (5, 12)), anchor)
        number = post(self.warehouse, old.revision).account_id
        five = export_audit(self.warehouse, number, [5], detail=True)
        nine = export_audit(self.warehouse, number, [9], detail=True)
        # Groups 5 and 9 carry the same reading and measure, but not the same slot.
        self.assertEqual(
            five['groups'][0]['measure'], nine['groups'][0]['measure'],
        )
        self.assertNotEqual(five['groups'][0]['ordinal'], nine['groups'][0]['ordinal'])
        with self.assertRaises((LakeError, ValueError)):
            verify_audit(five, anchor, [9], detail=True)
        spliced = json.loads(pack(nine))
        spliced['groups'][0]['measure'] = json.loads(pack(five))['groups'][0]['measure']
        spliced['proof']['openings']['9'] = json.loads(pack(five))['proof']['openings']['5']
        with self.assertRaisesRegex(LakeError, 'EVIDENCE_MISMATCH'):
            verify_audit(spliced, anchor, [9], detail=True)

    def test_empty_group_detail_bundle(self):
        old, anchor, new, _ = self.stage()
        self.accept(self.issue(old.revision, 'first', (9,)), anchor)
        self.accept(self.issue(old.revision, 'rest', (5, 12)), anchor)
        number = post(self.warehouse, old.revision).account_id
        bundle = export_audit(self.warehouse, number, [12], detail=True)
        self.close_source()
        self.close_warehouse()
        groups = verify_audit(detached(bundle), detached(anchor), (12,), detail=True)
        self.assertEqual(groups, [{
            'ordinal': 3, 'group_id': 12,
            'measure': {'count': 0, 'total_liters': '0', 'minimum_liters': None, 'maximum_liters': None},
            'observations': [],
        }])

    def test_redacted_anchor_hides_other_groups(self):
        old, anchor, new, _ = self.stage()
        first = self.issue(old.revision, 'first', (9,))
        expected = redact_anchor(anchor, (9,))
        self.assertEqual(first.anchor, expected)
        hidden = first.anchor['measure_commitments']['5']
        self.assertNotEqual(hidden, anchor['measure_commitments']['5'])
        self.assertNotEqual(hidden, anchor['detail_commitments']['5'])
        self.assertEqual(first.anchor['measure_commitments']['9'], anchor['measure_commitments']['9'])
        second = self.issue(old.revision, 'rest', (5, 12))
        self.assertEqual(second.anchor['measure_commitments']['5'], anchor['measure_commitments']['5'])
        self.assertNotEqual(second.anchor['measure_commitments']['9'], anchor['measure_commitments']['9'])
        # A parcel carrying a group never confirms a group it did not carry.
        self.accept(first, anchor)
        self.assertEqual(confirm(self.source, get_receipt(self.warehouse, 'first')), (5, 12))

    def test_replay_after_reopen_keeps_evidence(self):
        old, anchor, new, _ = self.stage()
        parcel = self.issue(old.revision, 'first', (9,))
        receipt = self.accept(parcel, anchor)
        self.open_warehouse()
        self.assertEqual(self.accept(DeliveryParcel.from_json(parcel.to_json()), detached(anchor)), receipt)
        self.assertEqual(confirm(self.source, receipt), (5, 12))
        self.assertEqual(load_parcel(self.source, 'first'), parcel)

