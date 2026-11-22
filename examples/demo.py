import json
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from lake.accounts.history import read
from lake.accounts.publication import post
from lake.db import connect_source, connect_warehouse
from lake.dispatch.confirmations import confirm
from lake.dispatch.parcels import DeliveryParcel, dispatch
from lake.dispatch.plans import plan_waves, replan
from lake.freeze.revisions import freeze
from lake.intake.batches import submit
from lake.receive.acceptance import accept
from lake.receive.receipts import get_receipt


def report(case_id, inputs, expected, actual, downstream_expected, downstream_actual, paths, oracle):
    if actual != expected or downstream_actual != downstream_expected:
        raise AssertionError(f'{case_id}: observed {actual!r} and {downstream_actual!r}')
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': case_id, 'input': inputs, 'expected': expected, 'actual': actual,
        'downstream_expected': downstream_expected, 'downstream_actual': downstream_actual,
        'code_paths': paths, 'oracle': oracle,
    }, ensure_ascii=False, sort_keys=True))


def run_shift(sample, source_path, warehouse_path):
    with closing(connect_source(source_path)) as source:
        for batch in sample['batches']:
            submit(source, sample['day_key'], batch['batch_id'], batch['rows'])
        manifest = freeze(source, sample['day_key'], [batch['batch_id'] for batch in sample['batches']], sample['group_ids'])
        revision = manifest.revision
        plan_waves(source, revision, {'morning': sample['old_selection']})
        old_wire = dispatch(source, revision, 'morning', wave='morning').to_json()

    with closing(connect_warehouse(warehouse_path)) as warehouse:
        accept(warehouse, DeliveryParcel.from_json(old_wire))

    with closing(connect_source(source_path)) as source, closing(connect_warehouse(warehouse_path)) as warehouse:
        replan(source, revision, {'evening': sample['new_selection']})
        new_wire = dispatch(source, revision, 'evening', wave='evening').to_json()
        old_receipt = get_receipt(warehouse, 'morning')
        pending = confirm(source, old_receipt)
        blocked = post(warehouse, revision)
        report(
            'v6', {'directory': sample['group_ids'], 'first_parcel': sample['old_selection']},
            {'receipt': [1, 3], 'source_pending': [2]},
            {'receipt': list(old_receipt.group_ids), 'source_pending': list(pending)},
            {'warehouse_missing': [2], 'account_id': None},
            {'warehouse_missing': list(blocked.missing_groups), 'account_id': blocked.account_id},
            ['lake/receive/receipts.py', 'lake/dispatch/confirmations.py', 'lake/dispatch/backlog.py', 'lake/accounts/readiness.py'],
            '从目录 1、2、3 删除旧件明确携带的 1、3 后，只剩正式空组 2。',
        )

    with closing(connect_warehouse(warehouse_path)) as warehouse:
        receipt = accept(warehouse, DeliveryParcel.from_json(new_wire))
        result = post(warehouse, revision)
        if result.account_id is None:
            raise AssertionError(f'account is still waiting for {result.missing_groups}')

    with closing(connect_source(source_path)) as source, closing(connect_warehouse(warehouse_path)) as warehouse:
        account = read(warehouse, result.account_id)
        totals = account.totals
        report(
            'v4.overlap_receipt', sample,
            {'receipt': [2, 3], 'source_pending': []},
            {'receipt': list(receipt.group_ids), 'source_pending': list(confirm(source, receipt))},
            {'groups': [1, 2, 3], 'first_parcels': ['morning', 'evening', 'morning'],
             'count': 2, 'total_liters': 18, 'minimum_liters': 7, 'maximum_liters': 11},
            {'groups': [entry.group.group_id for entry in account.groups],
             'first_parcels': [entry.first_parcel_id for entry in account.groups],
             'count': totals.count, 'total_liters': totals.total_liters,
             'minimum_liters': totals.minimum_liters, 'maximum_liters': totals.maximum_liters},
            ['lake/receive/acceptance.py', 'lake/receive/group_ledger.py', 'lake/accounts/rollup.py',
             'lake/accounts/publication.py', 'lake/accounts/history.py'],
            '组 1 的 7 L 与组 3 的 11 L 各贡献一次。实收的空组 2 关闭缺口。组 3 的首次来件是晨班旧件。',
        )
        print(f'{account.day_key} {account.account_id} 版次 {account.edition}，'
              f'{totals.count} 笔，{totals.total_liters} L，范围 {totals.minimum_liters} 至 {totals.maximum_liters} L')


def main():
    sample = json.loads(Path(__file__).with_name('day.json').read_text(encoding='utf-8'))
    with TemporaryDirectory() as directory:
        root = Path(directory)
        run_shift(sample, root / 'source.sqlite', root / 'warehouse.sqlite')


if __name__ == '__main__':
    main()
