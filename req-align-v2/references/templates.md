# 模板与清单（req-align-v2）

**模板即约束**：本文件的模板自带 `AC-N` / `RISK-N` / `BND-N` 占位槽位。复制模板就带上 ID，不填反而要主动删——这是遵守率最高的规则形态。脚本按下列格式解析，**改格式会让脚本失效**。

## 1. 落盘产物模板

产物目录：`docs/req-align-<yyyy-mm-dd>-<slug>/`（slug 用小写字母 / 数字 / 连字符）。
目录已存在时不覆盖，改用 `-2`、`-3` 递增后缀。

```text
docs/
├── req-align-history/
│   ├── index.md          # run 时间线
│   ├── boundaries.md     # 模块级边界台账（跨 run 沉淀主力）
│   └── pitfalls.md       # 项目级踩坑库
└── req-align-<yyyy-mm-dd>-<slug>/
    ├── align.md          # 六要素对齐文档
    ├── arch-risk.md      # 边界风险扫描 + 决议记录
    ├── acceptance.md     # 人工验收勾选清单
    └── handoff.json      # 机器契约（由 align_state.py sync 生成，禁止手写）
```

### 1a. `align.md`

```markdown
# 需求对齐：<标题>

日期: <yyyy-mm-dd> | slug: <slug> | 状态: 草稿 | 来源: <一句话>

## 🎯 目标

<一句话复述需求>

## 📦 范围

✅ 支持:
- <能力 1>
- <能力 2>

⛔ 暂不支持:
- <明确排除项 1>（理由: ...）

## 🔼 优先级

- P0（必须）: ...
- P1（应该）: ...
- P2（可以）: ...

## ✅ 验收标准

- AC-1 (P0) 输入 <A> → 输出 <B>
- AC-2 (P1) 当 <C> 时 → 行为 <D> 持续 <E>

## 🧱 架构边界风险

见 `arch-risk.md`（扫描表与决议记录）。

## ➡️ 下一阶段

判定: <直接推进 / 需 SDD 深化 / 先做架构发现>
去向: <架构发现 / SDD 规格 / 执行计划>
沿用的历史决策: <BND-N 沿用 / BND-N 覆盖（理由: ...） / 无>
```

**格式硬约束**（脚本解析依赖）：

- 验收行必须以 `- AC-<数字>` 开头，紧跟 `(P0|P1|P2)`，其后是可观察描述。
- ID 连续、唯一，从 `AC-1` 起。
- 每条验收需含 `→` / `当` / `若` / `Given` / `When` 之一的触发形态。

### 1b. `arch-risk.md`

两个二级标题**必须原样保留**（脚本按标题定位）；决议段用**三级标题**挂在「决议记录」之下。

```markdown
# 架构边界风险与决议：<标题>

## 🧱 边界风险扫描

| ID | 边界 | 风险 | 关联边界 | 建议验证阶段 | 状态 |
| --- | --- | --- | --- | --- | --- |
| RISK-1 | 数据流边界 | 谁生产谁消费未定 | BND-3 | 架构发现时用 trace_path 查调用链 | 待验证 |
| RISK-2 | 时序 / 事件流 | 未命中 | — | — | 未命中 |
| RISK-3 | 跨服务 / 跨模块 | 未命中 | — | — | 未命中 |
| RISK-4 | 持久化与领域模型 | 未命中 | — | — | 未命中 |
| RISK-5 | 多 Agent / 外部 API 契约 | 未命中 | — | — | 未命中 |
| RISK-6 | 可验证性 | 未命中 | — | — | 未命中 |

## 📌 决议记录

<!-- append-only：由 align_state.py resolve-risk 写入。首次落盘时本区块为空是正常的。 -->
```

首次落盘时不要预填决议段：`待验证` 行只有实际运行 `resolve-risk` 后才会切换为
`已决议` 并追加 `### RISK-1 — 数据流边界`、决议/理由/影响记录。

**格式硬约束**：

- 表格列顺序固定：`ID | 边界 | 风险 | 关联边界 | 建议验证阶段 | 状态`。
- `状态` 受控值：`未命中` / `待验证` / `已决议`。
- **扫描表数据行数必须 ≥ 6**（`risk-patterns.md` §2 清单六项逐项过）。未命中的也要占一行；`check_alignment.py` 对不足六行报 FAIL，对六类名称是否覆盖仅报 WARN（同义命名不能靠关键词硬判）。
- 决议段标题格式 `### RISK-<数字> — <边界名>`，ID 必须在扫描表中存在。
- **状态列只能由 `align_state.py resolve-risk` 修改**，它在同一次原子写里同时追加决议段并改状态，杜绝两处不一致。

### 1c. `acceptance.md`

```markdown
# 验收清单：<标题>

来源: `align.md` 的「✅ 验收标准」 | 执行完成后逐条核对；勾选还须有证据，收尾需通过风险与项目门禁。

- [ ] AC-1 输入 <A> → 输出 <B>
- [ ] AC-2 当 <C> 时 → 行为 <D> 持续 <E>

## P0 验证设计

| AC | 正常例及预期 | 失败/边界例及预期 | 用户操作与验收者 | 自动化断言 |
| --- | --- | --- | --- | --- |
| AC-1 | 输入 A → 输出 B | 无权限输入 A → 拒绝且不触达受保护数据 | 用户：操作 1、2，观察 B | 契约/集成测试路径 |

## 证据

<!-- close-ac 追加，格式：AC-N | <step 或 -> | <验证证据> -->

## 未通过记录

<!-- fail-ac 追加，格式：AC-N | <观察到的现象> -->
```

**格式硬约束**：

- 条目必须是 `- [ ] AC-<数字> ...`，AC 集合与 `align.md` **完全一致**（多一个少一个都 FAIL）。
- **勾选只能由 `align_state.py close-ac` 执行**，必须带证据（`--run-cmd` / `--manual --observer` / 旧式 `--evidence`）——防止"打了勾但没证据"。
- 每条 P0 AC 都要在「P0 验证设计」中有正反例、可判定的预期结果与负责人；用户可见行为写真实操作路径，纯内部 AC 的人工列写「N/A—仅自动化断言」。
- P0 验证设计的内容由审核者核对；当前 `check_alignment.py` 不判断正反例是否真能证明功能，校验通过不等于功能已通过。
- 「证据」小节每行三种形态（同 AC 以最新一条为准）：
  - `- AC-N | step | [run exit=0 rev=<16位hex|no-git> out=<8位hex>] <命令>` —— `close-ac --run-cmd CMD` 由脚本执行命令，非零退出/超时拒绝并不改任何文件；`rev` 为执行完成后的代码指纹，`out` 为输出哈希；对已关闭 AC 再跑一次即刷新证据。
  - `- AC-N | step | [manual observer=<NAME> rev=<...>] <观察>` —— `close-ac --manual --observer NAME --evidence TEXT`，只记录署名观察者。
  - 旧式自报文本（裸 `--evidence`）：仅 P1/P2 可接受，P0 在 `--strict-closure` 下 FAIL；并发的代码改动还会拒绝以保留前缀 `[run ` / `[manual ` 开头的裸证据，以免伪造脚本记录。
- 代码指纹 = `HEAD` + 已改/暂存/未跟踪且未被忽略文件的路径与内容哈希，**排除顶层 `docs/`**（`close-ac` 自己会改 `docs/req-align-*/`）。非 git 仓库为 `no-git`，新鲜度比较只 WARN。
- 以上均不证明命令有意义（`true` 也能通过 `--run-cmd`）；见 SKILL.md「脚本无法证明的事」。更改已关闭 AC 的正文/优先级时先运行 `fail-ac` 重新打开，再改文档并 `sync`，不得沿用旧证据。

### 1d. `handoff.json`

**由 `align_state.py sync` 从上面三份 Markdown 派生，禁止手写。** Markdown 是人类可读事实来源，JSON 是机器契约。

```json
{
  "contract_version": "1",
  "slug": "global-service-catalog",
  "date": "2026-09-02",
  "title": "底层服务全局台账",
  "next_stage": "exec-plan",
  "stages": [
    {"stage": "sdd", "dir": "docs/sdd-2026-09-02-global-service-catalog/"},
    {"stage": "exec-plan", "dir": "docs/exec-plan-2026-09-02-global-service-catalog/"}
  ],
  "acceptance": [
    {"id": "AC-1", "priority": "P0", "text": "输入 X → 输出 Y", "closed": false, "evidence": null, "step": null}
  ],
  "risks": [
    {"id": "RISK-1", "boundary": "数据流边界", "state": "待验证", "boundary_ref": "BND-3"}
  ],
  "boundaries_touched": ["BND-3"],
  "source_sha256": {
    "align.md": "<该文件原始字节的 SHA-256 小写十六进制值>",
    "arch-risk.md": "<该文件原始字节的 SHA-256 小写十六进制值>",
    "acceptance.md": "<该文件原始字节的 SHA-256 小写十六进制值>"
  }
}
```

`next_stage` 受控值：`sdd` / `arch-discovery` / `exec-plan`。
`risks[].state` 受控值：`未命中` / `待验证` / `已决议`。
`source_sha256` 三项是示意占位，必须由脚本生成真实的 64 位哈希，不能手填。旧契约若缺少此字段，需先运行 `align_state.py sync <run_dir>`；源文件改动未同步时，校验与下游步骤推进均会失败。已关闭 AC 的正文或优先级变更须先 `fail-ac`，不能通过重跑 `sync` 沿用旧证据。

### 1d-2. `reviews.json`（独立审核记录，非 handoff 的一部分）

由 `align_state.py record-review` 追加，数组元素字段：`id`（REV-N）、`reviewer`、`author`、`scope`（`milestone` / `time-backstop` / `final`）、`verdict`（`approved` / `changes-requested`）、`summary`、`rev`（记录时的代码指纹前 16 位）、`at`。`reviewer` 与 `author` 不能相同（忽略大小写）。`--strict-closure` 要求**最新一条**是针对当前指纹的 `final` + `approved`；其后任何新审核都会使其失效。文件损坏按失败处理，不当作空。

### 1e. `req-align-history/boundaries.md`（模块级边界台账）

**跨 run 沉淀的主力**。以模块为主键、一行一条决策、强制单句结论——这是可检索性的关键（run 为主键的长句摘要检索不出东西）。

```markdown
# 架构边界台账

一行一条决策，以模块为主键。生命周期受控值：生效 / 已被覆盖。
只允许 `boundary_state.py` 写入；覆盖时脚本会同步在旧 run 的 arch-risk.md 插入失效横幅。

| ID | 模块 | 边界结论（一句话） | 生命周期 | 来源 run | 被谁覆盖 |
| --- | --- | --- | --- | --- | --- |
| BND-7 | 底层服务归属 | 服务是全局台账，先配置服务再挂钩租户 | 生效 | 2026-09-02-global-service-catalog | — |
| BND-4 | 底层服务归属 | 审批时填写首次服务配置 | 已被覆盖 | 2026-08-29-tenant-user-service-approval | BND-7 |
```

### 1f. `req-align-history/pitfalls.md`（项目级踩坑库）

与个人级 `~/.claude/lessons.md` 分工：个人级存**跨项目**技术教训，本文件存**本项目边界**上的坑。同类不新增行，`count+1`。

```markdown
# 项目级踩坑库

每条挂在一个 BND 上；下次对齐命中该边界时由 `boundary_state.py scan` 自动带出。

| ID | 关联边界 | 现象 | 根因 | 防护规则 | count |
| --- | --- | --- | --- | --- | --- |
| PIT-2 | BND-3 | SSE「非流式」跨层歧义导致范围被误读 | 谈范围前未区分前端事件流与 LLM token 流两层 | 涉及流式的范围决策必须先声明影响哪一层 | 2 |
```

### 1g. `req-align-history/index.md`（run 时间线）

台账承担"边界现在是什么"，本文件只承担"什么时候做过哪些 run"。

```markdown
# 需求对齐 run 时间线

| 日期 | slug | 下一阶段 | 验收闭环 | 风险决议 | 链接 |
| --- | --- | --- | --- | --- | --- |
| 2026-09-02 | global-service-catalog | exec-plan | 3/8 | 1/2 | ../req-align-2026-09-02-global-service-catalog/ |
```

「验收闭环」与「风险决议」由 `boundary_state.py history-sync` 重算，不手填。

## 2. 澄清问题清单

按价值排序，只挑 1-3 个问，能靠上下文推断就不问：

- **交付物**：系统 / 功能 / 修复 / 调研？可接受的最小可用版本是什么？
- **不变量**：哪个环节坏了最致命？允许什么程度的不完美？
- **边界**：有没有明确不做的事？依赖哪些现有系统 / 数据 / API？
- **验收**：你用什么方式判断"做完了"？能举一个输入输出例子吗？
- **风险**：是否牵扯实时性 / 顺序 / 一致性 / 跨系统？同类需求之前是否返工过？

两处人工闸门（台账新增/变更、高危边界命中）**不占**这 1-3 个额度。

## 3. SDD 模板（仅当判定"需 SDD 深化"时使用）

把自然语言验收改写为 Given/When/Then 规格，**保留原 AC-N 编号**（禁止重新编号）：

```text
AC-3 Specification:

Given:
  <前置条件，如 same character_id>
When:
  <触发行为，如 generating different scenes>
Then:
  must preserve: <必保属性列表>

Allowed variation:
  <允许的变化范围，如 emotion / pose / lighting>
```

## 4. 可观察性检查表

判断规则：一条验收能否被一个测试断言？不能 = 不可观察 = 必须改写。

| 不可观察 | 可观察改写 |
| --- | --- |
| 角色一致性要好 | 同 character_id 跨场景：五官 / 发型 / 服饰 / 年龄感不变，仅表情 / 姿势 / 光照可变 |
| 系统要稳定 | 1000 次请求错误率 < 0.1%，无崩溃，P95 延迟 < 2s |
| 输出正常 | 输入 story → 输出 10 个分镜，每个含 镜头 / 角色 / 动作 / Prompt |
| 体验流畅 | 用户发送消息后 3s 内首 token 到达，流式过程中无中断回退 |

高频不可观察词（脚本会拒绝）：要好 / 稳定 / 正常 / 流畅 / 自然 / 合理 / 高效 / 完善 / 可靠 / 好看 / 好用。
