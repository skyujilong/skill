---
name: sdd-v2
description: 把 req-align-v2 对齐后的需求写成完整、可读、可机检的规格（SDD / 完整需求文档），产出 docs/sdd-<date>-<slug>/。触发：写或深化 SDD/规格/spec、"规格化"、"完整需求文档"、handoff.json 的 next_stage 为 sdd、把已对齐的 AC 展开成 Given/When/Then 验收矩阵。不重新对齐需求、不做架构决策、不写代码；没有上游 run 目录时先让用户跑 req-align-v2。
---

# sdd-v2：需求规格化

链路第 2 阶段：`req-align-v2 -> SDD -> 架构发现 -> execute-plan-plus-v2`。
上游的 AC-N / RISK-N / BND-N 原样沿用，**永不重新编号**。

## 范围

- 做：把已对齐需求写成完整规格（背景、范围、功能/非功能需求、边界、验收矩阵）。
- 不做：重新对齐需求（回 req-align-v2）、架构决策（下一阶段）、写代码。

## 前置

需要 req-align-v2 的 run 目录（`docs/req-align-<date>-<slug>/`）且含 `handoff.json`。没有就停下，告诉用户先跑 req-align-v2 并 `align_state.py sync`。

## 流程

1. 读 `handoff.json`、`align.md`、`acceptance.md`（范围、AC、RISK 状态）。
2. 建目录 `docs/sdd-<yyyy-mm-dd>-<slug>/`：slug 与 run 目录**完整一致**，与 run 目录同在 `docs/` 下。
3. 按 `references/spec-guide.md` 写 `README.md`、`01-overview.md`、`acceptance-matrix.md`（可选 `data-model.md`、`api-contracts.md`）。
4. 跑检查：`python3 scripts/check_sdd.py <sdd_dir> --run-dir <run_dir>`，FAIL 先修；WARN 逐条处理或说明理由。
5. 登记：`python3 <req-align-v2>/scripts/align_state.py stage-add <run_dir> --stage sdd --dir <sdd_dir>`。
6. 独立通读矩阵：让**不是作者**的审阅者对照 `align.md` 逐条判断每行规格是否真的覆盖该 AC。如何按工具（Claude Code / Codex / WorkBuddy）创建独立审阅者，见 `execute-plan-plus-v2/references/review.md`（相对路径）。

## 新需求与已关闭 AC

SDD 过程中发现**新需求**：不要只在 SDD 里加 AC。走 req-align-v2：改 `align.md` + `acceptance.md`，重跑 `align_state.py sync`，再回来补矩阵行。
改动**已关闭**的 AC 正文/优先级：先 `fail-ac` 重开，再同步，旧证据不再有效。
新风险同理：回 `arch-risk.md` 追加 RISK-N。

## 硬门禁

| 门禁 | 脚本 | 拦什么 | 怎么修 |
| --- | --- | --- | --- |
| 上游新鲜度 | check_sdd.py | handoff.json 无 `source_sha256` 或与 align/arch-risk/acceptance.md 当前字节不符 | `align_state.py sync <run_dir>` 后重跑 |
| 目录命名/位置 | check_sdd.py；stage-add | slug 取自 **run 目录名**（handoff `slug` 须一致）；目录名非 `sdd-<日期>-<完整 slug>`、不与 run 同级 | 改名/移到 `docs/`；slug 不符先 sync |
| 必备文件 | check_sdd.py；stage-add | README / 01-overview / acceptance-matrix 缺失或为空 | 补文件 |
| 矩阵与 AC 一一对应 | check_sdd.py | 扫描围栏外**所有**合规表格并汇总：缺 AC、跨表重复、自造/改号 id | 补行；新 id 走 req-align-v2 |
| 规格形态 | check_sdd.py | Given→When→Then（或 给定→当→则）未按序齐全（应当/否则/规则 等普通词不算）、占位、覆盖模块为空 | 重写该行 |
| P0 失败/边界例 | check_sdd.py | P0 行无失败/边界关键词（整词匹配；单个「空」不算） | 在规格或备注补一例 |
| 概览必备章节 | check_sdd.py | 缺 目标/范围/功能需求/非功能需求/错误与边界 | 补二级标题 |
| 登记 | stage-add | 未登记则执行计划门禁不放行 | 跑第 5 步命令 |

WARN（不拦截）：概览漏引某 AC、README 未提上游 run、开放问题缺负责人。

## 脚本无法证明的事

- **内容是否正确**：脚本只看结构与 AC 覆盖；一句语法完备但错误的 Given/When/Then 照样 PASS。
- 规格是否真的覆盖 AC 原意、非功能指标是否合理、边界是否穷尽——需要第 6 步的独立通读。
- G/W/T 与 P0 失败例的关键词检查只是提示级（advisory-grade）：能挡明显漏写，挡不住刻意凑词，关键词出现不等于用例有意义。
- `stage-add` 只登记目录与文件存在，不是内容核查。
- 概览里 AC 的引用是否逐字，脚本只查 id 出现，不比对文字。

## 文件

- `references/spec-guide.md`：规格结构、Given/When/Then 规则、示例。
- `scripts/check_sdd.py`：只读检查，退出码 0 通过 / 1 有失败 / 2 用法或上游契约错误。
- `evals/evals.json`：行为用例（无 runner，仅作契约文档）。
