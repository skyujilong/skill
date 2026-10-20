---
name: req-align-v2
description: 把模糊需求做工程化对齐，并产出可被下游阶段机器消费的契约：查阅模块级边界台账与项目踩坑库、澄清目标、划定支持/暂不支持边界、定优先级、产出带稳定 ID（AC-N）的可观察验收标准与人工验收勾选清单、扫描架构边界风险（RISK-N）、落盘 docs/req-align-<date>-<slug>/（align.md + arch-risk.md + acceptance.md + handoff.json）并沉淀边界决策（BND-N），最后判定下一阶段。闭环回写（勾选验收、决议风险、覆盖旧决策）全部由脚本执行且带失效双向标记；验收证据可由脚本执行命令生成（close-ac --run-cmd）并绑定代码版本，独立审核记入 reviews.json，收尾 --strict-closure 校验证据新鲜度与 final 审核。触发场景：用户给出模糊或一句话需求（"我要做一个 X 系统"、"帮我加个功能"、"这个需求怎么做"）、需求缺边界或验收标准、需求触碰系统边界（事件流/SSE/跨服务/多 Agent/持久化/外部 API 契约）需要在写代码前先识别风险、需要沉淀架构决策以防后期漂移、需要一份执行完成后可人工核对的验收清单、需要为 execute-plan-plus-v2 准备上游契约、或评审已有需求文档是否缺边界、缺可观察验收、缺架构风险识别。
---

# 模糊需求工程化对齐（req-align-v2）

对齐"我们是不是想做同一个东西"，并把结果沉淀成**可被后续阶段机器消费的结构化产物**。
本 skill 只做四层链路的第一层，不越界：

```text
需求对齐(req-align-v2) → SDD 规格化 → 架构发现 → 执行计划(execute-plan-plus-v2)
```

## 职责边界

- **做**：定位需求所在层 → 检索边界台账与踩坑库 → 最少澄清 → 对齐六要素（带 AC-N）→ 边界扫描（带 RISK-N）→ 判定下一阶段 → 落盘 per-run 目录 + `handoff.json` → 沉淀边界决策（BND-N）。
- **不做**：完整 SDD 规格生成、架构设计、写代码、拆执行计划。检测到下游工作直接转交对应 skill 或提示用户。

## 命名规范

产物目录 `docs/req-align-<yyyy-mm-dd>-<slug>/`；slug 用小写字母 / 数字 / 连字符；**目录已存在时绝不覆盖**，改用 `-2`、`-3` 递增后缀。
四阶段共用同一 slug（`sdd-` / `architecture-discovery-` / `exec-plan-` 同形），这样 `ls docs/ | grep <slug>` 一眼看全链路。
完整规范与中间层目录形态见 `references/downstream-contract.md`。

## 核心流程（6 步）

### Step 1 定位需求所在层

| 层 | 用户的话 | 动作 |
| --- | --- | --- |
| 需求层 | "我要做一个漫画生成系统" | 本 skill 主场，进入 Step 2 |
| SDD 层 | "角色一致性必须可验证" | 跳过对齐，给 `references/templates.md` §3 的 SDD 模板入口 |
| 架构层 | "用 ScenePlanner Agent + ShotPlanner" | 不做需求对齐，转架构评审（用 codebase-memory `trace_path` 查调用链） |
| 执行层 | "第一步建 domain model" | 已是计划，转 `execute-plan-plus-v2` |

### Step 2 检索边界台账与踩坑库

在澄清之前先看"这个边界以前是不是已经定过了、在这里踩过什么坑"：

```bash
python3 scripts/boundary_state.py scan --keywords <模块名>,<关键词> [--history-dir docs/req-align-history]
```

- 输出 `no-hit` → 直接进 Step 3，不打断用户，也不提这件事。
- **只读 `scan` 的输出，不要读整份 `boundaries.md` / `pitfalls.md`**：台账随项目线性增长，读全量会让上下文成本跟着涨；`scan` 只返回命中行 + 挂在其上的踩坑。
- 命中 `生效` 条目且本次要**沿用** → 当作既有上下文带入 Step 4/5，不打断用户。
- 命中的踩坑（`↳ [PIT-N] 坑xN`）要在本次对齐里显式规避，并在 `align.md` 的「下一阶段」处写明沿用了哪些 BND。
- 命中 `⚠️ 已被覆盖` 条目 → 它已失效，改用其 `被 BND-N 覆盖` 指向的那条。
- 本次需要**推翻**某条 `生效` 条目 → 走 Step 6 的台账变更闸门，不得自行决定。

### Step 3 澄清（最少问题原则）

只问最高价值的 1-3 个问题（清单见 `references/templates.md` §2）：交付物是什么、最关键的不变量、已知边界约束。能靠上下文推断时就不问。两处人工闸门不占这个额度。

### Step 4 对齐六要素

按 `references/templates.md` §1a 模板输出。模板自带 ID 槽位，照抄即可：

- 🎯 **目标**：一句话复述。
- 📦 **范围**：✅ 支持 / ⛔ 暂不支持——**"暂不支持"必填**，显式边界是第一条工程沉淀。
- 🔼 **优先级**：P0 / P1 / P2。
- ✅ **验收标准**：每条写成 `- AC-1 (P0) 输入 X → 输出 Y`，**可观察、可验证**。禁止"要好 / 稳定 / 正常 / 流畅"这类不可观察词（脚本会拒绝）。每条 P0 AC 在 `acceptance.md` 配正常例、失败/边界例、可判真假的预期结果；用户可见行为还需写具体手工操作和验收者。内部规则可标记无需人工操作，但必须指向自动化断言。
- 🧱 **架构边界风险**：正文落在 `arch-risk.md`。
- ➡️ **下一阶段**：见 Step 6。

### Step 5 架构边界扫描

按 `references/risk-patterns.md` §2 的六类清单逐项过，填 `arch-risk.md` 扫描表（`RISK-N` + `关联边界` 列）。命中的只**标记风险 + 建议验证阶段**，不在此解决。未命中的也占一行写"未命中"。

**🚪 人工闸门（高危边界命中）**：命中时序 / 事件流、跨服务 / 跨模块、外部 API 契约任一类时，用 `AskUserQuestion` 让用户选验证方式（codebase-memory `trace_path` / 最小可运行脚本 / 查当前版本官方文档 / 用户直接给结论），**不要自行决定验证手段**。

### Step 6 判定下一阶段 + 落地

| 判定 | 条件 | 去向 |
| --- | --- | --- |
| 直接推进 | 验收可观察 + 无高危边界 | 执行计划 |
| 需 SDD 深化 | 存在"机器和测试可验证"缺口 | `references/templates.md` §3 SDD 模板 |
| 先做架构发现 | 存在高危边界（事件流 / 跨服务契约不明） | codebase-memory `trace_path` 查真实调用链 |

落地顺序（**先对话确认，再落文件**；用户只要对话结果时不落盘）：

1. 写三份 Markdown（`align.md` / `arch-risk.md` / `acceptance.md`），`acceptance.md` 的 AC 集合必须与 `align.md` 完全一致、**首次落盘全部未勾选**。P0 的正反例与用户路径按 `references/templates.md` §1c 落盘；没有可判定结果的 AC 不进入执行计划。
2. 生成机器契约（**禁止手写 `handoff.json`**）：
   ```bash
   python3 scripts/align_state.py sync docs/req-align-<date>-<slug>/
   ```
3. **🚪 人工闸门（台账新增 / 变更）**：本次确认了新的长期边界结论，或要推翻既有 `生效` 条目时，先用 `AskUserQuestion` 向用户列出「拟写入的单句结论 / 影响的既有 BND / 覆盖理由」，得到确认后才写：
   ```bash
   # 新增
   python3 scripts/boundary_state.py add --run docs/req-align-<date>-<slug>/ \
       --module "<模块>" --statement "<一句话结论>" --from-risk RISK-N \
       --confirmed-by human --gate-outcome adopted
   # 覆盖既有（自动双向标记：台账两行 + 旧 run 失效横幅 + 时间线）
   python3 scripts/boundary_state.py supersede BND-4 --by docs/req-align-<date>-<slug>/ \
       --new-statement "<新的一句话结论>" --reason "<覆盖理由>" \
       --confirmed-by human --gate-outcome adopted
   ```
   `--confirmed-by` / `--gate-outcome` 是必填参数，但只**记录声称的确认方**，不证明真的问过人；必须先实际执行上面的 `AskUserQuestion`。
4. 更新时间线并自检：
   ```bash
   python3 scripts/boundary_state.py history-sync docs/req-align-<date>-<slug>/
   python3 scripts/check_alignment.py docs/req-align-<date>-<slug>/
   ```

## 闭环义务（脚本执行，禁止手改）

`arch-risk.md` 的状态列、`acceptance.md` 的 checkbox、`boundaries.md` 的任何一行——**都不要用编辑器改**。理由见 `references/risk-patterns.md` §4。

| 什么时候 | 跑什么 |
| --- | --- |
| 一条风险被验证 / 拍板 | `align_state.py resolve-risk <run_dir> RISK-N --decision T --reason T --impact T` |
| 一条验收被验证通过（命令可复现） | `align_state.py close-ac <run_dir> AC-N --run-cmd "<验证命令>" [--cwd DIR] [--timeout SEC] [--evidence 备注] --step <步骤名>`：脚本自己执行，非零退出/超时拒绝关闭且不改文件，记录 `[run exit=0 rev=<16hex\|no-git> out=<8hex>] CMD`；对已关闭 AC 重跑即刷新证据（最新一条为准） |
| 一条验收靠人工观察 | `align_state.py close-ac <run_dir> AC-N --manual --observer NAME --evidence "<观察>"`，记录 `[manual observer=NAME rev=...]`；与 `--run-cmd` 互斥 |
| 旧式自报证据 | 裸 `--evidence "<文本>"`：仅 P1/P2 可接受（P0 在 `--strict-closure` 下 FAIL）；并发代码改动还会拒绝以保留前缀 `[run ` / `[manual ` 开头的裸证据 |
| 一次独立审核完成 | `align_state.py record-review <run_dir> --reviewer R --author A --scope milestone\|time-backstop\|final --verdict approved\|changes-requested --summary T`：写 `reviews.json`，绑定当前代码指纹；reviewer 不得等于 author |
| 一条验收核对不通过 | `align_state.py fail-ac <run_dir> AC-N --observed "<现象>"` |
| 已关闭 AC 的描述或优先级要修改 | 先 `fail-ac` 重新打开并记录变更原因，再改 `align.md` / `acceptance.md`，最后 `sync`；同步后下游重新审计覆盖与受影响步骤 |
| 踩了一个与某边界相关的坑 | `boundary_state.py pitfall-add --boundary BND-N --phenomenon T --root-cause T --guard T` |
| 中间层产物落盘（登记只证明目录名与强制文件存在，不是内容核查） | `align_state.py stage-add <run_dir> --stage sdd\|arch-discovery\|exec-plan --dir PATH` |

`resolve-risk` 在同一次原子写里改状态列并追加决议段；`close-ac` 强制证据；
`supersede` 同时完成台账与旧 run 横幅——这三处漂移不可能再发生。写命令在重建 `handoff.json` 失败时会把 Markdown 回滚。
`sync` 失败即关闭（fail closed）：`handoff.json` 缺失但已有勾选；已关闭 AC 在 `acceptance.md` 被取消勾选却无「未通过记录」条目；已关闭 AC 的文字/优先级漂移（必须先 `fail-ac`）。
代码指纹 = `HEAD` + 已改/未跟踪且未忽略文件的内容哈希，**排除顶层 `docs/`**；非 git 仓库为 `no-git`，新鲜度比较只 WARN。
用户可见行为不能仅凭单测关闭；已关闭 AC 的文字或优先级变动不得沿用旧绿色状态；变更、新增 AC 或改动风险决议都要通知下游重审计划。下游若无法追踪受影响范围，应重验全部 P0 AC。

### 脚本无法证明的事

`--run-cmd true` 也能通过；reviewer 只是记录的名字，未经认证；`reviews.json` 与 `acceptance.md` 可被手改；
独立性仍取决于另一位人类或全新的子代理；没有变异测试引擎；evals 没有运行器；
无上游的通用模式只有流程约定加 `final_gate.py` 的步骤检查。脚本只能让缺失与过期可被拒绝。

## 下游交接

下游以 `handoff.json` 为机器契约（schema 见 `references/templates.md` §1d），拿到 slug、`next_stage`、`stages`、`acceptance[AC-N]`、`risks[RISK-N]`。执行器还会按 `source_sha256` 核对同目录三份 Markdown 是否在上次同步后被修改；这不是从散文重推需求。旧 handoff 缺指纹时先运行 `sync`；修改已关闭 AC 的正文或优先级，必须先 `fail-ac` 再修改并同步。
`execute-plan-plus-v2` 会据此写自己的 `upstream.json`，并在每个 step `complate` 前校验其覆盖的 AC 已闭环——把"事后回写"变成"推进的前置条件"。
中间层目录规范与 ID 透传规则见 `references/downstream-contract.md`。

## 自检

```bash
python3 scripts/check_alignment.py docs/req-align-<date>-<slug>/ [--history-dir PATH] [--strict-closure]
```

- 默认模式：落盘后自检，允许验收全未勾选、风险未决议。
- `--strict-closure`：收尾门禁，要求全部 AC 已勾选且带证据、无 `待验证` 遗留；另要求 P0 证据为脚本验证记录（`[run exit=0 …]` / `[manual …]`）且 rev 与当前代码指纹一致，并且 `reviews.json` **最新一条**是针对当前指纹的 `final` `approved`（之后任何新审核都使其失效）。非 git 下这两项新鲜度比较仅 WARN。由 `execute-plan-plus-v2/scripts/final_gate.py` 一并调用。
- 退出码：`0` 无 FAIL / `1` 有 FAIL / `2` 参数或路径错误。WARN 不影响退出码。

## 引用

- `references/templates.md` — 产物模板（自带 ID 槽位）、`handoff.json` schema、台账/踩坑库/时间线模板、澄清清单、SDD 模板、可观察性检查表。
- `references/risk-patterns.md` — 边界失败模式与六类扫描清单、阶段判定、当场写 vs 事后回写的实测数据与脚本约束。
- `references/downstream-contract.md` — 四阶段命名规范、SDD 与架构发现的强制目录形态、ID 透传规则。
- `scripts/align_state.py` — run 内写操作唯一入口。
- `scripts/boundary_state.py` — 跨 run 沉淀（台账 / 踩坑库 / 时间线）。
- `scripts/check_alignment.py` — 产物自检与收尾门禁。
