# 下游阶段契约与命名规范（req-align-v2）

> **强制力声明（请照实看待）**：`align_state.py stage-add` 校验目录命名、同级位置和强制文件；
> `execute-plan-plus-v2` 在关联计划推进时要求所需阶段已登记、文件仍在且上游风险无待验证项。
> 不调用 `stage-add` 不能绕过执行门禁。SDD 与架构发现目前没有对应 skill；这些检查
> **不验证规格或架构结论的内容正确性**，仍须独立审核，不能把文件存在当作已验收。
> `stage-add` 登记只是"目录与强制文件存在"的登记，不是内容核查。
>
> 收尾侧：执行计划以 `execute-plan-plus-v2/scripts/final_gate.py <plan_dir> --req-align-scripts <本 skill 的 scripts 目录>` 一次性调用
> `audit_coverage.py`、`check_alignment.py --strict-closure`、`boundary_state.py history-sync`。
> `--strict-closure` 额外要求：P0 证据为脚本验证（`[run exit=0 ...]`/`[manual ...]`）且 rev 与当前代码指纹一致，
> 以及 `reviews.json` 最新一条是针对当前指纹的 `final` `approved` 审核（非 git 仓库下新鲜度比较仅 WARN）。

## 1. 四阶段命名规范

| 阶段 | 目录名 | 谁产出 |
| --- | --- | --- |
| 需求对齐 | `docs/req-align-<yyyy-mm-dd>-<slug>/` | req-align-v2 |
| SDD 规格 | `docs/sdd-<yyyy-mm-dd>-<slug>/` | 暂无 skill，按本文件规范手工/即兴产出 |
| 架构发现 | `docs/architecture-discovery-<yyyy-mm-dd>-<slug>/` | 同上 |
| 执行计划 | `docs/exec-plan-<yyyy-mm-dd>-<slug>/` | execute-plan-plus-v2 |
| 跨 run 沉淀 | `docs/req-align-history/` | req-align-v2 |
| 运行痕迹 | `docs/.skill-metrics/runs.jsonl` | 各脚本（人工事后查看用） |

规则：

1. **slug 是链路的可见纽带**，各阶段共用同一个 slug。这样 `ls docs/ | grep <slug>` 一眼看全链路。
   纯时间戳命名（无 slug）的目录无法一眼看出对应关系，只能逐个 grep `original-plan.md`。
2. 同日同 slug 多次需求对齐 → 将新 run 的 slug 定为 `<原 slug>-2`、`<原 slug>-3`，
   **绝不覆盖**已存在目录；后续阶段必须继承该 run 的**完整** slug。
   不能只给某个中间阶段目录追加 `-2` 来代替它所登记的上游 slug。
3. **命名不承担机器关联职责。** 实测两天内出现 4 个相近 slug（`sse-streaming` / `sse-transport` /
   `frontend-sse-chat` / `sse-async-start`），靠名字相似度做程序 join 会错配。
   机器关联的唯一事实来源是 `handoff.json`（上游侧）与 `upstream.json`（下游侧）里的显式路径指针。
   **命名解决人眼可读，指针解决程序正确，两件事不能混同。**
4. 存量的时间戳式目录不改名；两种命名形态会长期并存。

## 2. `sdd-<date>-<slug>/` 强制形态

```text
docs/sdd-<yyyy-mm-dd>-<slug>/
├── README.md                # 必须：入口与阅读顺序
├── 01-overview.md           # 必须：范围与关键决策摘要
├── acceptance-matrix.md     # 必须：以 AC-N 为行键的规格矩阵
├── data-model.md            # 可选
└── api-contracts.md         # 可选
```

`acceptance-matrix.md` **必须以上游 AC-N 为行键**：

```markdown
| AC | 规格（Given/When/Then） | 覆盖模块 | 备注 |
| --- | --- | --- | --- |
| AC-3 | Given 同 character_id / When 跨场景生成 / Then 五官发型服饰年龄感不变 | image-pipeline | 允许表情姿势光照变化 |
```

下游不得自造编号——必须以 AC-N 为行键，否则各层编号互不映射。

## 3. `architecture-discovery-<date>-<slug>/` 强制形态

```text
docs/architecture-discovery-<yyyy-mm-dd>-<slug>/
├── architecture.md           # 必须：分层与依赖方向
├── flows-and-boundaries.md   # 必须：数据流 / 时序 / 边界归属
├── decisions.md              # 必须：以 RISK-N 为键的验证结论
└── data-model.md             # 可选
```

`decisions.md` 只是**过程记录**；一条风险真正被决议，必须回写到上游：

```bash
python3 <req-align-v2>/scripts/align_state.py resolve-risk docs/req-align-<date>-<slug>/ RISK-3 \
    --decision "..." --reason "..." --impact "..."
```

不回写就等于没决议——下次对齐扫不到它，会重新踩同一个边界。

## 4. ID 透传规则

- 下游**只能引用与细化** AC-N / RISK-N / BND-N，**禁止重新编号**。
- 中间层发现了新需求 → 回 `align.md` 追加一条 `AC-<下一个编号>`，重跑 `align_state.py sync`，
  **不在中间层私自新增编号**。
- 中间层发现了新边界风险 → 回 `arch-risk.md` 追加一行 `RISK-<下一个编号>`。
- `exec-plan-*/requirements.md` 的 `R1..Rn` 可以保留（实现视角分组），但每个 R 必须写
  `Covers: AC-1, AC-3`，且 `audit_coverage.py` 会校验它与 `step.json` 的 `covers` 并集一致。
- 已关闭 AC 的正文/优先级变更 → 先用 `fail-ac` 重开（记录原因），再同步 Markdown 与 JSON；旧证据不再证明新契约。新增/修改 AC 后，下游须重新执行覆盖审计、检查已完成步骤的受影响代码与测试，重验后才可再次关闭。仅检查编号连续不等于验证内容仍有效。
- `next_stage` 指向 SDD / 架构发现时，先登记对应阶段并完成其要求的验证；`待验证` 风险必须先决议，执行计划才能进入编码。`stage-add` 目前只验证文件存在，**不验证**规格内容或架构结论的正确性，后续审核不能省略。

## 5. 登记与执行门禁

每个中间层产物落盘后立刻登记，脚本会校验与上游同级的 `docs/` 目录、精确命名
`<阶段前缀><yyyy-mm-dd>-<完整上游 slug>`、强制文件齐全，不合规则拒绝：

```bash
python3 <req-align-v2>/scripts/align_state.py stage-add docs/req-align-<date>-<slug>/ \
    --stage sdd --dir docs/sdd-<date>-<slug>/
```

`--stage` 取值：`sdd` / `arch-discovery` / `exec-plan`。
若 `handoff.json` 的 `next_stage` 指向中间层但 `stages` 仍为空，`check_alignment.py` 会给 WARN；
关联执行计划的步骤转换会 FAIL，不允许开始编码。登记只证明文件存在，不证明内容正确。
