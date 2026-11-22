# 渠湾监测湖

渠湾监测中心的白班把闸站测读编为日表，运输班按波次把冻结资料送到异地，夜班在断源环境检查齐备并签发日账。后续核账可按原账号查阅各组的测读出处和实收出处。

## 运行

需要 Python 3.11，仅使用标准库。在项目根目录运行。

```text
python3 -B check_project.py
python3 -B -m unittest discover -s tests -t .
python3 -B -m examples.run_demos
```

`check_project.py` 是物化时提供的标准核验入口。演示以 `examples/day.json` 为输入，在独立临时目录建立两库，完成旧件确认丢失、重开、重划、重领确认、重叠件交付和按号核账。完整回归也使用独立临时库。

## 白班成版

`lake.db.connect_source(path)` 和 `connect_warehouse(path)` 打开各自 SQLite 库并执行幂等初始化。调用方关闭连接。两类库各有独立初始化脚本。`initialize_source(db)` 与 `initialize_warehouse(db)` 可在空闲连接上重复执行，保留此前经业务入口保存的数据。样例只向演示创建的临时库提交。

- `lake.intake.batches.submit(db, day_key, batch_id, rows)` 接纳一批，返回 `StationBatch`。`rows` 是有序列表或元组，每行为 `(group_id, source, liters)`，`liters` 是整数升或 `None`。缺测和重复出现的来源均保留，用批号及从 1 起算的批内位置定位。同批号同日同序同文重投返回原批，异文和非法行整批拒绝。
- `lake.intake.day_assembly.assemble_day(db, day_key, batch_ids)` 按批清单及各批原行序预览草稿。
- `lake.freeze.revisions.freeze(db, day_key, batch_ids, group_ids)` 追加一个不可变 `FrozenManifest`。目录非空且组号唯一，支持任意目录顺序和非连续组号。批清单可空，批号须唯一且同日，所有测读组须声明。`lake.freeze.manifest.load_manifest` 和 `load_frozen_groups` 按版取原材料，组输出按目录顺序。

日表键、批号、来源、波次和交付号使用非空 UTF-8 字符串，首尾无空白且无 NUL。组号、版号和持久位置是正的 64 位有符号整数。测读值、组和日合计使用精确 Python 整数，持久材料中的升量以规范十六进制文本保存。读数零参与计数和极值，缺测只保留出处。没有有效值的组保留正式组并返回零笔、0 L 和空极值。

## 运输与实收

- `lake.dispatch.plans.plan_waves(db, revision, waves)` 安排第一轮计划。`waves` 是波次名到所选组序列的字典，各波所选组来自当时待送组。计划可以只安排部分待送组。已有计划时用 `replan(db, revision, waves)` 原子替换，空字典可清空计划。计划替换保留已发行件和已确认覆盖。`load_wave` 查当前波次的固定选组。
- `lake.dispatch.parcels.dispatch(db, revision, parcel_id, group_ids=...)` 按明确选组发行，或使用 `wave=...` 选择当前计划的一个波次。两种参数二选一，材料按目录序固定。原件的身份由交付号绑定到版号和所选组，同号同参可复领，同号异参拒绝。需要脱离当前计划重领旧件时用 `load_parcel(db, parcel_id)`。`DeliveryParcel.to_json()` 和 `DeliveryParcel.from_json(text)` 提供自含材料的往返表示。
- `lake.receive.acceptance.accept(db, parcel)` 将材料提交到异地库。首件建立完整目录，后续件必须与同版目录一致。每组校验身份、来源位置及由读数复算的计量，重叠正文须相同。冲突整包拒收。每个逻辑组只保留一份归约贡献和首次成功交付件的出处。
- `lake.receive.receipts.get_receipt(db, parcel_id)` 按成功件复领 `Receipt`，同件重投也返回等价确认。确认涵盖该件的全部实际组，包括此前已收的同正文组。
- `lake.dispatch.confirmations.confirm(db, receipt)` 核对版号、交付号和与原件完全匹配的组覆盖，持久合并后返回按目录序的待补组。`lake.dispatch.backlog.pending_groups(db, revision)` 单独查询待补。确认不会随着波次切换失效。搭配使用的一份源湖和异地仓共享版号命名域，交付和确认通过受信交班渠道传递。

## 夜班核账

`lake.accounts.publication.post(db, revision)` 返回 `PostResult`。已知版尚缺组时，`account_id` 为 `None`，`missing_groups` 是按目录序的缺组。正式空组到仓前同样列为待补。齐备时返回账号和空缺组列表。同版重复发布返回原账号。`lake.accounts.history.read(db, account_id)` 按号返回冻结版、目录序组计量、有序来源、首次实收件和全日计量，未知账号返回 `None`。每笔有效测读保留原升量，日总量为组总量之和，日极值来自所有有效组，全日无有效测读时两项均为空。新版签账保留旧号的固定明细。

非法业务输入、未知批、未知版、未知件及冲突通过 `lake.db.LakeError` 报告，`code` 可用于程序处理。涉及写入的业务入口拥有各自的本地事务，须以空闲连接调用。SQLite 错误原样向调用方报告，失败事务回滚。

## V2 限组核账

白班在同一份源湖冻结日表时固定核账依据。异地仓用它接纳局部交付，外部复核员用它核对后来取得的计量件或明细件。调用方经独立可信的交班渠道获得锚和本次交付应走的模式，并原样保留锚。交付件和核账件由另外的渠道送达，其自带内容不能代替独立锚。两库沿用原来的版号命名域。

入口与调用约定如下：

```text
manifest, anchor = lake.freeze.revisions.freeze(
    source, day_key, batch_ids, group_ids, with_anchor=True)
parcel = lake.dispatch.parcels.dispatch(source, revision, parcel_id, group_ids=[...])  # 或 wave=...
wire = parcel.to_json()                         # 含 format/anchor/evidence 的 V2 件
receipt = lake.receive.acceptance.accept(warehouse, DeliveryParcel.from_json(wire), anchor=anchor)
bundle = lake.accounts.history.export_audit(warehouse, account_id, [group_id], detail=False)
groups = lake.accounts.history.verify_audit(bundle, anchor, [group_id], detail=False)
```

### 冻结和接纳

- `lake.freeze.revisions.freeze(db, day_key, batch_ids, group_ids, *, with_anchor=False)` 省略选项时沿用原返回值。选 `with_anchor=True` 时返回 `(FrozenManifest, anchor)`。锚为能经 JSON 往返的字典，至少含整数 `revision`，其余证明字段由实现定义。锚与该版目录、组材料同次冻结，发行或重领不得改变冻结依据。
- 使用原 `dispatch` 选组和 `load_parcel` 复领。V2 件通过 `DeliveryParcel.to_json()` 和 `DeliveryParcel.from_json(text)` 传递。顶层仍包含 `parcel_id`、`manifest`、`groups` 及其原业务字段，新增字段用于标明 V2 和承载证据。原 V1 线格式仍可读写。
- `lake.receive.acceptance.accept(db, parcel, *, anchor=None)` 在 V2 交班时由调用方逐件传入独立获取的预期锚。即使仅实收一组，也核对锚所固定的完整目录身份，以及该组在原目录中的序位、组号、计量和原文。原文包括原行顺序、读数、缺测、批号、批内位置及站点出处。V2 件缺锚，或带 V2 预期锚的交班收到没有相应证据的旧格式件，均拒收。已经接纳的版次保持其模式及锚绑定，后续实收与重投也须核对。V1 交班仍用原调用。
- 证据、实收和确认资格一起提交。材料或锚不符抛 `LakeError`，失败的首次投件不得建立实收或确认，已有记录保持原样。合法件仍返回原 `Receipt`，可按原入口复领和结清。正式空组也须实收，`post` 齐备后才按版签账。

### 出件和复核

- `lake.accounts.history.export_audit(db, account_id, group_ids, *, detail=False)` 从原账号导出核账件。`group_ids` 沿用发行选组规则，传非空、无重复的组号列表或元组。按冻结目录序输出，可在源湖已关闭且异地库重开后导出。未知账号、无 V2 依据的旧账号或非法选组抛 `LakeError`。
- `lake.accounts.history.verify_audit(bundle, trusted_anchor, group_ids, *, detail=False)` 只使用传入的值，无需两库和签发进程。`group_ids` 是复核方预期获准的组，`detail` 是预期粒度，两者独立于来件。成功返回目录序的 `groups` 列表。错版、错位、正文或计量不符、粒度或范围不符、无效证据及坏格式抛 `ValueError`，不给出部分结果。
- `bundle` 是能经 JSON 往返的字典，含 `manifest`、`detail`、`groups`、`proof`。`manifest` 用 `FrozenManifest.to_data()` 的字段，线上组目录是数组。`detail` 为布尔值。`groups` 的每项含从 1 起算的原目录 `ordinal`、`group_id` 和 `measure`，计量字段及升量编码沿用 `GroupMeasure.to_data()`。`detail=True` 时每项再含 `observations` 数组，即对应组的原序 `Observation.to_data()`。`proof` 的格式由实现决定。计量件和明细件各自能以同一固定版的可信锚独立核验。
- 锚和出件可暴露必要的目录身份和序位。计量件只开启获准组的计量。锚和出件不得携带全日合计、未披露的原文、未获准组的计量，或允许对这些隐藏内容直接试猜验证的材料。拿到其他获准组的正确材料也不能据此开启隐藏内容。可信渠道和获准组的决定由调用方负责。允许读全版或重算证明。

实现上，冻结锚为每组保存两枚互不相干的盐化承诺：计量承诺与明细承诺，绑定版号、日键、版次、从 1 起算的目录序位和组号。锚只含版本身份、目录和承诺摘要，不含读数、出处、批号或合计。V2 交付件携带按所选组裁剪的锚副本和这些组的盐；未选组的位置换成同域不可逆摘要，因而拿到一个正确件也无法据其核对另一隐藏组。核账件的 `proof` 只开获准组对应粒度的盐。`verify_audit` 以可信锚重算承诺来判定版次、序位、组号、计量和原文，并在任何字段不符时抛错而不返回部分结果。

### 用两版同值组核账

`examples.audit_case` 提供同一天的两批输入。旧目录为 `[5,9,12]`，新版为 `[9,5,12]`。组 5 和组 9 都各有一笔 7 L，组 12 正式为空。第 9 组旧出处是 `gate/b-old`，新出处是 `gate/b-new`。`python3 -B -m examples.audit_case` 从冻结到重开读回两份 V1 日账。加 `--changed-source` 可观察基线中把首件出处改为 `gate/substituted` 后仍然签出 14 L 的对照。夹具的 `detached_anchor` 可复制已经独立取得的锚，`replace_first_source` 可只替换交付件首行的出处。

在 V2 样例中先冻结两版并分别保存独立锚。关闭源库，仅投旧版第 9 组的换文件，预期拒收且该交付号不可领确认。再实收原件，确认只覆盖第 9 组。此时缺组为 `[5,12]`，无账号。补齐后旧版签出两笔、14 L、极值均为 7 L。新版完整交付后另行签账。重开异地仓，按旧号分别导出第 9 组的计量件和明细件。关闭异地库后用旧锚核验，结果为原目录第 2 位、计量一笔 7 L。明细还应返回 `gate/b-old`、原批号 `audit-morning` 和批内第 2 位。组 12 单独获准时，结果为原目录第 3 位、零笔、0 L、空极值。

替换为新版材料、同值的第 5 组材料、改动计量，或用不同的预期组和粒度核验，都应拒绝。V1 账号仍可正常领账，对它请求 V2 核账件应拒绝。

### 运行交付

基线运行清单连接原回归和原演示。完成 V2 后沿用 `.pointwise-runtime.json` 的 `version` 为 `1`、`kind` 为 `cli`。`setup` 为准备命令的参数数组列表，可为空，`verify` 和 `demo` 各为一条命令的参数数组。让 `verify` 保留原完整回归并核验上述冻结、实收和按号出件的联动，核验失败须非零退出。用 `demo` 展示换文被拒和重开仓后凭旧锚断库核账的实际结果。

`check_project.py` 先跑完整回归，再以临时库执行 `examples.v2_audit.run` 的冻结、换文拒收、补齐签账、重开导出与断库核验；任一失败以非零退出。`demo` 入口为 `examples.run_demos`，依次运行原 `examples.demo`、`examples.audit_case` 的两版同值组日账，以及 V2 换文拒收和旧号断库核账。

