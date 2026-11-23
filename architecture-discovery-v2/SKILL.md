---
name: architecture-discovery-v2
description: 架构发现（四阶段链路第三层）：用真实证据（读代码/调用链追踪、最小脚本、当前官方文档、用户明确确认）验证 req-align-v2 标为「待验证」的高危边界风险（RISK-N），产出 docs/architecture-discovery-<date>-<slug>/（architecture.md + flows-and-boundaries.md + decisions.md），并把每条决议用 align_state.py resolve-risk 回写上游。触发：用户说"架构发现/验证架构风险/验证边界/查真实调用链"、handoff.json 的 next_stage 为 arch-discovery、arch-risk.md 里有状态「待验证」的风险（事件流/SSE、跨服务、外部 API 契约）、需要在写代码前确认分层与依赖方向。不写生产代码、不重新对齐需求、不写 SDD。
---

# 架构发现（architecture-discovery-v2）

```text
req-align-v2 → SDD → 架构发现(本 skill) → execute-plan-plus-v2
```

## 范围

- 做：逐条验证 `待验证` 风险并留证据；写架构文档、流程与边界归属；决议回写上游。
- 不做：写生产代码；重新对齐需求（发现需求本身有问题 → 回 req-align-v2）；写 SDD（用 sdd-v2）。

## 前置条件

需要 req-align-v2 的 run 目录 `docs/req-align-<date>-<slug>/` 且含 `handoff.json`。没有就告诉用户先跑 req-align-v2（及其 `align_state.py sync`），不要自己手写 handoff.json。
下文 `<req-align-v2>` 指该 skill 的目录。

## 工作流

1. **列风险**：`python3 scripts/list_risks.py <run_dir>`，得到 `待验证` 的 RISK-N、边界、风险、建议阶段。
2. **选验证方式（人工闸门）**：对时序/事件流、跨服务/跨模块、外部 API 契约三类高危边界，**必须问用户**用哪种方式验证（读代码调用链 / 最小脚本 / 查当前官方文档 / 用户直接确认），不得静默选定。同 req-align-v2 Step 5。
3. **取证**：工具无关——有代码图/调用链工具就用它，否则读代码 + grep；或跑最小脚本并记录真实输出；或抓取当前版本官方文档；或引用用户明确的确认原话。证据写入 `decisions.md`（格式见 `references/discovery-guide.md`）。禁止凭记忆断言框架/API 行为。
4. **写文档**：`architecture.md`、`flows-and-boundaries.md`，目录 `docs/architecture-discovery-<yyyy-mm-dd>-<上游完整 slug>/`（上游 slug 为 `x-2` 时必须保留 `-2`，不得加其他后缀）。保留上游 AC-N / RISK-N / BND-N，不重编号。
5. **回写上游**（每条风险一次）：
   `python3 <req-align-v2>/scripts/align_state.py resolve-risk <run_dir> RISK-N --decision ... --reason ... --impact ... --confirmed-by human|agent`
   只在 decisions.md 里写而没回写 = 不算决议。成功后在该段补 `- 已回写: yes`。
6. **自检**：`python3 scripts/check_arch_discovery.py <dir> --run-dir <run_dir>`。
7. **登记**：`python3 <req-align-v2>/scripts/align_state.py stage-add <run_dir> --stage arch-discovery --dir <dir>`。
8. **独立通读**：决议质量脚本无法判断。按 `execute-plan-plus-v2/references/review.md` 的方法，在 Claude Code / Codex / WorkBuddy 里新建独立审阅者通读 decisions.md 与证据，再交付。

应跨 run 长期保留的模块级决策，另用 `<req-align-v2>/scripts/boundary_state.py add` 写入边界台账（该步在 req-align-v2 有自己的人工闸门，这里只指路，不代办）。

## 硬闸门

| 闸门 | 违反后果 |
| --- | --- |
| 每个非「未命中」风险有 `## RISK-N` 决议段，不得多出上游没有的编号 | check FAIL |
| 每段含结论/证据类型(code\|script\|doc\|user)/证据/影响，非占位 | check FAIL |
| handoff 中该风险已是 `已决议`（resolve-risk 已执行） | check FAIL；写 `已回写: yes` 但未执行也 FAIL |
| handoff.json 新鲜：`source_sha256` 与 align/arch-risk/acceptance.md 当前字节一致 | check FAIL；先 `align_state.py sync <run_dir>` |
| 目录名 slug 取自 run 目录名（handoff `slug` 须一致）、精确一致且与 run 同级 | check FAIL，stage-add 也会拒绝命名不符 |
| 三个必需文件非空 | check FAIL（stage-add 只检查文件存在，不拒绝空文件） |
| 高危边界的验证方式由人选定 | 无脚本强制，违反即流程失败 |

## 脚本证明不了什么

- 证据内容是否真实、是否足以支持结论——脚本不核对（不打开 file:line，不重跑命令，不访问 URL）。
- 脚本只证明：每条风险有类型化证据、有决议、已回写，文档结构齐全。
- 标题 WARN（分层/依赖、选型、数据流/时序/边界）、`code`/`doc`/`script` 证据格式检查都只是提示级（advisory-grade），不拦截也不证明内容。
- 因此第 8 步独立通读建议执行；`stage-add` 登记也只是目录与文件存在的登记，不是内容核查。

详细格式、六类风险验证方法与示例：`references/discovery-guide.md`。
