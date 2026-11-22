"""V2 limited-group audit sample: freeze anchors, reject a swapped file, then
reopen the warehouse and check the old account number with only the stored
anchor and an independent expectation."""
import json
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from lake.accounts.history import export_audit, read, verify_audit
from lake.accounts.publication import post
from lake.db import LakeError, connect_source, connect_warehouse, pack
from lake.dispatch.confirmations import confirm
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


def detached(anchor):
    """Copy the separately obtained anchor across a JSON handoff."""
    return json.loads(pack(anchor))


def substitute_first_source(wire, source="gate/substituted"):
    data = json.loads(wire)
    data["groups"][0]["observations"][0]["source"] = source
    return pack(data)


def _expect_error(label, action, code):
    try:
        action()
    except LakeError as exc:
        if exc.code != code:
            raise AssertionError(f"{label}: expected {code}, got {exc.code}") from exc
        return
    raise AssertionError(f"{label}: expected {code}, but the action succeeded")


def run(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    source_path = root / "v2-source.sqlite"
    warehouse_path = root / "v2-warehouse.sqlite"
    with closing(connect_source(source_path)) as source:
        submit(source, DAY, OLD_BATCH, OLD_ROWS)
        submit(source, DAY, NEW_BATCH, NEW_ROWS)
        old, old_anchor = freeze(source, DAY, (OLD_BATCH,), OLD_ORDER, with_anchor=True)
        new, new_anchor = freeze(source, DAY, (NEW_BATCH,), NEW_ORDER, with_anchor=True)
        old_anchor, new_anchor = detached(old_anchor), detached(new_anchor)
        swapped_wire = substitute_first_source(
            dispatch(source, old.revision, "old-first", group_ids=(9,)).to_json()
        )
        group_five = dispatch(source, old.revision, "old-five", group_ids=(5,)).to_json()
        original_wire = dispatch(source, old.revision, "old-first", group_ids=(9,)).to_json()
        old_rest_wire = dispatch(source, old.revision, "old-rest", group_ids=(5, 12)).to_json()
        new_wire = dispatch(source, new.revision, "new-all", group_ids=NEW_ORDER).to_json()

    # The source lake is closed: every acceptance below uses carried material.
    with closing(connect_warehouse(warehouse_path)) as warehouse:
        _expect_error("swapped first parcel", lambda: accept(
            warehouse, DeliveryParcel.from_json(swapped_wire), anchor=old_anchor,
        ), "EVIDENCE_MISMATCH")
        _expect_error("missing anchor", lambda: accept(
            warehouse, DeliveryParcel.from_json(original_wire),
        ), "MISSING_ANCHOR")
        _expect_error("no receipt for the rejected parcel", lambda: get_receipt(
            warehouse, "old-first",
        ), "UNKNOWN_RECEIPT")
        _expect_error("still no account", lambda: post(warehouse, old.revision), "UNKNOWN_REVISION")

        receipt = accept(warehouse, DeliveryParcel.from_json(original_wire), anchor=old_anchor)
        if receipt.group_ids != (9,):
            raise AssertionError("the first accepted parcel must carry exactly group 9")
        blocked = post(warehouse, old.revision)
        if (blocked.account_id, blocked.missing_groups) != (None, (5, 12)):
            raise AssertionError(f"old edition should wait for groups 5 and 12, got {blocked}")
        accept(warehouse, DeliveryParcel.from_json(old_rest_wire), anchor=old_anchor)
        old_result = post(warehouse, old.revision)
        old_account = read(warehouse, old_result.account_id)
        accept(warehouse, DeliveryParcel.from_json(new_wire), anchor=new_anchor)
        new_result = post(warehouse, new.revision)

    with closing(connect_source(source_path)) as source:
        confirmed = confirm(source, receipt)
        if confirmed != (5, 12):
            raise AssertionError("the delivery only confirms the group it actually carried")

    # Reopen the warehouse, export by the original account number, close again.
    with closing(connect_warehouse(warehouse_path)) as warehouse:
        measure_bundle = export_audit(warehouse, old_result.account_id, [9])
        detail_bundle = export_audit(warehouse, old_result.account_id, (9,), detail=True)
        empty_bundle = export_audit(warehouse, old_result.account_id, [12])
        # Keep the exported wires across the close so only carried values remain.
        measure_bundle = detached(measure_bundle)
        detail_bundle = detached(detail_bundle)
        empty_bundle = detached(empty_bundle)
        _expect_error("substitute the new edition", lambda: verify_audit(
            detail_bundle, detached(new_anchor), [9], detail=True,
        ), "WRONG_REVISION")
        _expect_error("wrong granularity", lambda: verify_audit(
            detail_bundle, detached(old_anchor), [9], detail=False,
        ), "WRONG_DETAIL")
        _expect_error("wrong scope", lambda: verify_audit(
            detail_bundle, detached(old_anchor), [5, 9], detail=True,
        ), "WRONG_SCOPE")

    # The warehouse is closed too.  Only the stored anchor and expectations remain.
    measure = verify_audit(measure_bundle, detached(old_anchor), [9])
    detail = verify_audit(detail_bundle, detached(old_anchor), (9,), detail=True)
    empty = verify_audit(empty_bundle, detached(old_anchor), [12])
    if measure != [{"ordinal": 2, "group_id": 9, "measure": {
            "count": 1, "total_liters": "7", "minimum_liters": "7", "maximum_liters": "7"}}]:
        raise AssertionError(f"unexpected measure material: {measure}")
    observation = detail[0]["observations"][0]
    if (detail[0]["ordinal"], observation["source"], observation["batch_id"], observation["position"]) != (
        2, "gate/b-old", OLD_BATCH, 2,
    ):
        raise AssertionError(f"unexpected detail material: {detail}")
    if empty != [{"ordinal": 3, "group_id": 12, "measure": {
            "count": 0, "total_liters": "0", "minimum_liters": None, "maximum_liters": None}}]:
        raise AssertionError(f"unexpected empty-group material: {empty}")

    result = {
        "day": DAY,
        "old_revision": old.revision,
        "new_revision": new.revision,
        "old_account": old_result.account_id,
        "new_account": new_result.account_id,
        "old_totals": old_account.totals.to_data(),
        "first_receipt": list(receipt.group_ids),
        "source_pending_after_first": list(confirmed),
        "swapped_first_parcel": "EVIDENCE_MISMATCH",
        "measure_audit": measure,
        "detail_audit": detail,
        "empty_group_audit": empty,
    }
    print("V2_AUDIT " + json.dumps(result, ensure_ascii=False, sort_keys=True))
    print(f"换文交付号 old-first 拒收；旧号 {old_result.account_id} 断库后凭旧锚核验："
          f"第 2 位组 9 一笔 7 L，来源 {observation['source']}，"
          f"原批 {observation['batch_id']} 第 {observation['position']} 位。")
    return result


def main():
    with TemporaryDirectory() as directory:
        run(Path(directory))


if __name__ == "__main__":
    main()
