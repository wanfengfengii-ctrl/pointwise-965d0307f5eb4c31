"""Run the original shift demo, the V1 audit contrast, and the V2 audit demo."""
import json
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from examples import audit_case, demo, v2_audit
from lake.db import connect_source, connect_warehouse


def run_v1_audit(root):
    with closing(connect_source(root / 'audit-source.sqlite')) as source:
        revisions, wires = audit_case.issue_v1(source)
    with closing(connect_warehouse(root / 'audit-warehouse.sqlite')) as warehouse:
        account_ids = audit_case.receive_v1(warehouse, revisions, wires, False)
    with closing(connect_warehouse(root / 'audit-warehouse.sqlite')) as warehouse:
        return audit_case.account_summary(warehouse, account_ids, False)


def main():
    sample = json.loads(Path(__file__).with_name('day.json').read_text(encoding='utf-8'))
    with TemporaryDirectory() as directory:
        root = Path(directory)
        demo.run_shift(sample, root / 'source.sqlite', root / 'warehouse.sqlite')
        print('V1_AUDIT ' + json.dumps(run_v1_audit(root), ensure_ascii=False, sort_keys=True))
        v2_audit.run(root / 'v2')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
