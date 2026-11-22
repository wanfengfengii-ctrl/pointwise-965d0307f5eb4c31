"""Sample inputs and V1 observations for the limited group audit."""
import argparse
import json
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from lake.accounts.history import read
from lake.accounts.publication import PostResult, post
from lake.db import connect_source, connect_warehouse, pack
from lake.dispatch.parcels import DeliveryParcel, dispatch
from lake.freeze.revisions import freeze
from lake.intake.batches import submit
from lake.receive.acceptance import accept
from lake.receive.receipts import get_receipt


DAY = "2026-06-18"
OLD_ORDER = (5, 9, 12)
NEW_ORDER = (9, 5, 12)
OLD_BATCH = "audit-morning"
NEW_BATCH = "audit-afternoon"
OLD_ROWS = ((5, "gate/a", 7), (9, "gate/b-old", 7))
NEW_ROWS = ((5, "gate/a", 7), (9, "gate/b-new", 7))


def stage_samples(source):
    submit(source, DAY, OLD_BATCH, OLD_ROWS)
    submit(source, DAY, NEW_BATCH, NEW_ROWS)


def detached_anchor(anchor):
    """Copy the separately obtained source value across a JSON handoff."""
    return json.loads(pack(anchor))


def replace_first_source(wire, source):
    """Change the first observation without rebuilding proof or measure."""
    data = json.loads(wire)
    data["groups"][0]["observations"][0]["source"] = source
    return pack(data)


def issue_v1(source):
    stage_samples(source)
    old = freeze(source, DAY, (OLD_BATCH,), OLD_ORDER)
    new = freeze(source, DAY, (NEW_BATCH,), NEW_ORDER)
    first = dispatch(source, old.revision, "audit-first", group_ids=(9,))
    rest = dispatch(source, old.revision, "audit-rest", group_ids=(5, 12))
    moved = dispatch(source, new.revision, "audit-moved", group_ids=NEW_ORDER)
    return (old.revision, new.revision), tuple(parcel.to_json() for parcel in (first, rest, moved))


def receive_v1(warehouse, revisions, wires, changed_source):
    first, rest, moved = wires
    if changed_source:
        first = replace_first_source(first, "gate/substituted")
    first_parcel = DeliveryParcel.from_json(first)
    receipt = accept(warehouse, first_parcel)
    if receipt.group_ids != (9,) or get_receipt(warehouse, receipt.parcel_id) != receipt:
        raise AssertionError("first receipt must cover exactly group 9")
    if post(warehouse, revisions[0]) != PostResult(None, (5, 12)):
        raise AssertionError("old version still needs groups 5 and 12")
    accept(warehouse, DeliveryParcel.from_json(rest))
    accept(warehouse, DeliveryParcel.from_json(moved))
    ids = tuple(post(warehouse, revision).account_id for revision in revisions)
    if any(account_id is None for account_id in ids):
        raise AssertionError("complete versions must both post")
    return ids


def account_summary(warehouse, account_ids, changed_source):
    expected_sources = ("gate/substituted" if changed_source else "gate/b-old", "gate/b-new")
    results = []
    for account_id, order, expected_source in zip(account_ids, (OLD_ORDER, NEW_ORDER), expected_sources):
        account = read(warehouse, account_id)
        if account is None or tuple(entry.group.group_id for entry in account.groups) != order:
            raise AssertionError("account directory differs from frozen order")
        entry = account.groups[order.index(9)]
        sources = tuple(row.source for row in entry.group.observations)
        totals = account.totals
        if sources != (expected_source,) or (totals.count, totals.total_liters) != (2, 14):
            raise AssertionError("unexpected V1 account contents")
        results.append({"account_id": account_id, "revision": account.revision,
                        "group_9_ordinal": order.index(9) + 1, "group_9_sources": sources,
                        "count": totals.count, "total_liters": totals.total_liters})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changed-source", action="store_true", help="observe the V1 contrast with a changed first parcel")
    args = parser.parse_args()
    with TemporaryDirectory() as directory:
        root = Path(directory)
        with closing(connect_source(root / "source.sqlite")) as source:
            revisions, wires = issue_v1(source)
        with closing(connect_warehouse(root / "warehouse.sqlite")) as warehouse:
            account_ids = receive_v1(warehouse, revisions, wires, args.changed_source)
        with closing(connect_warehouse(root / "warehouse.sqlite")) as warehouse:
            print(pack(account_summary(warehouse, account_ids, args.changed_source)))


if __name__ == "__main__":
    main()
