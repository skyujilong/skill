# Claude Code Skills 集合

本仓库收录了几个可以直接在 [Claude Code](https://docs.anthropic.com/claude/docs/claude-code) 中使用的自定义 Skill（用户级 Skill）。把它们放到 `~/.claude/skills/` 下之后，Claude Code 会在合适的时机自动触发，也可以用 `/<skill-name>` 显式调用。

## 已收录的 Skill

### 1. `execute-plan-plus` —— 大型计划的可恢复执行工作流

用于把一个又长又大的实施计划，拆分成"可以随时被 `/compact` 打断、又能安全从磁盘恢复"的执行流程。

它做的事情：

- 把用户原始计划**原文**存到 `docs/exec-plan-<时间戳>/original-plan.md`，避免后续被 LLM 改写走样。
- 生成一份有序的 `step.json` 作为**唯一的进度源**（保留 `runing` / `complate` 这两个拼写）。
- 生成一份 `split-audit.md`，对照原始计划做覆盖度审计，防止漏项。
- 只对**当前 3 步**展开详细的 mini-plan，避免一次性铺开庞大文档。
- 每完成一步立即验证；每 3 步做一次 compact checkpoint，提醒用户运行 `/compact`。
- 通过 `scripts/update_step_state.py` 修改状态，保证原子写入 + 状态转移合法。

适用场景：跨天/跨多次会话推进一个大重构、大迁移、多阶段落地时。

### 2. `orchestrate-plan` —— Plan 的自主编排执行 loop

用于把一份**已批准的 plan** 交给「主 agent 只派发、子 agent 干活」的自主 loop 执行，全程尽量少人工介入，但代码质量闸门一个不少。

它做的事情：

- **主 agent 只当调度员**：派发任务、收结构化回报、更新状态、出报告——**从不亲自写代码、也不亲自跑验收**。
- 执行前先派子 agent **LLM 自审 plan**（可行性 / 覆盖度 / 拆分顺序）；审出致命问题才上报请示，否则自动继续。
- 每一步交**独立执行子 agent**实现（按文件类型加载对应 `*-engineering` 规范），再交**独立验收子 agent**跑 typecheck / 测试 / lint。
- 验收失败就派修复子 agent 修、再验收，**最多 3 轮**；3 轮还不过 → 判定「规划这条路走不通」→ 立即停掉整个流程并出**详细中止报告**。
- 全部通过后，再派**整体 review 子 agent** + **codebase 图谱验证子 agent**（用 codebase-memory 校验调用链 / 契约 / 死代码 / 架构）。
- 状态存在 `docs/orchestrate-plan-<时间戳>/`，**每次调用一个独立目录、绝不覆盖**；支持中断后 `list` → 选中 → 从未完成步骤**恢复续跑**（不重置 3 轮预算）。
- 状态经 `scripts/run_state.py`（`init` / `list` / `status` / `update`）修改，原子写 + 转移合法 + 前序未完成不许开工。

适用场景：需求已梳理成 plan、想让 Claude 自主分步执行并保证质量时。它与 `execute-plan-plus` 互补——后者是单 agent 抗 `/compact` 的串行执行器，前者是多 agent 编排 + 独立验收 + 失败中止 + 整体 review。

### 3. `use-worktree` —— Git Worktree 并行开发管理

用于快速创建/列出/删除 git worktree，让你可以在多个分支上**同时并行开发**而无需来回切换分支。

它做的事情：

- 在**同级目录**下按 `{project-name}-worktree-{branch-name}` 命名创建 worktree。
- 自动识别项目类型并安装依赖：Python (`uv sync`)、Node.js (`pnpm install`)、Rust (`cargo`)、Go (`go mod`)、Java (`mvn`)，也支持 `frontend/` + `backend/` monorepo。
- `list` 时自动检查每个 worktree 是否 dirty / locked，并输出结构化结果。
- `delete` 前会检查未提交改动 + 是否已合并到主分支，需要用户明确确认。
- 所有操作都走 `scripts/worktree_manager.py`，避免边界情况（`node_modules`、`.venv`、缓存目录等）导致的删除失败。

适用场景：需要同时跑多个 feature/fix 分支、或者想在不打断当前工作的前提下临时切到另一个分支排查问题。

### 4. `python-engineering` —— Python 工程规范

约束 LLM 写 Python 时遵循真正的工程范式，而不是「一个 dict 传到底」的脚本写法。

它强调的规范：

- **类型建模优先**：数据有已知结构就建类型（`@dataclass` / `Pydantic` / `TypedDict` / `Enum`），跨边界的 `Dict[str, Any]` 视为坏味道。
- **函数单一职责**：一个函数只做一件事，禁巨型函数，用 guard clause 压平嵌套。
- **完整类型标注**：公共函数全标注，`Any` 是需要理由的逃生口而非默认值。
- **显式报错**：用具体异常表达失败，禁 `None`/`-1` 哨兵返回、禁 `except: pass`。
- **不可变 + 纯函数**：默认 `frozen`，把 IO 推到边缘让核心逻辑可测。
- 附带一份「收尾前自查清单」和 `references/patterns.md` 扩展案例库（错误层级、Protocol、IO 分离、边界解析等）。

适用场景：写任何 Python 代码时自动引导；也适合让它 review / 重构现有 Python。

### 5. `react-engineering` —— React 工程规范

约束 LLM 写 React（含 React + TypeScript）时遵循组件设计范式，而不是写出 300 行的巨型组件。

它强调的规范：

- **组件原子化**：小而单一职责，展示组件 vs 容器组件分离，组件过大立即拆分。
- **逻辑抽 custom hook**：有状态/副作用逻辑抽成 `useX`，组件体保持声明式。
- **禁巨型 hook**：hook 也要单一职责，大 hook 拆成可组合的小 hook。
- **props 精确建模**：接口化、用 discriminated union 表达变体、禁 `any`。
- **状态最小化**：只存唯一真相源，其余在 render 里派生，别用 `useEffect` 同步。
- **effect 只做真同步**：只用于对接外部系统，附带 cleanup + 完整依赖数组。
- 附带「收尾前自查清单」和 `references/patterns.md`（custom hook 抽取、compound component、状态就近、避免 effect 等）。

适用场景：写任何 React 组件 / hook / 前端 UI 时自动引导；也适合 review / 重构现有组件。

### 6. `nodejs-engineering` —— Node.js 工程规范

约束 LLM 写 Node.js(后端 / 服务 / 脚本,TypeScript 优先)时遵循后端工程范式,而不是回调套回调、`process.env` 满天飞、错误被吞的写法。

它强调的规范：

- **异步正确性**(Node 头号 bug 源):`async/await`、禁 floating promise、独立任务用 `Promise.all` 并发、不阻塞事件循环。
- **分层架构**:controller 只做校验/组装,业务逻辑进 service,数据访问进 repository,禁胖 controller。
- **边界校验**:请求体 / 参数 / env / 外部响应都是 `unknown`,用 zod 等在边界解析成类型;`as` 强转不算校验。
- **错误传播**:类型化错误层级 + 集中式错误处理,区分「运行时错误」与「程序 bug」,禁 `catch {}` 吞错。
- **配置与安全**:env 启动时校验成类型化配置注入,禁散落的 `process.env`;参数化查询、不 `eval` 输入、不硬编码密钥。
- **资源管理**:连接池、大数据用 stream、优雅关闭;结构化日志而非 `console.log`。
- 附带「收尾前自查清单」和 `references/patterns.md`(错误中间件、依赖注入、streaming、优雅关闭、配置模块等)。

适用场景：写任何 Node 服务 / API / 脚本时自动引导;也适合 review / 重构现有后端代码。

### 7. `vue3-engineering` —— Vue 3 工程规范

约束 LLM 写 Vue 3(Composition API + `<script setup>` + TypeScript)时遵循组件设计范式,而不是写出 400 行、响应式还悄悄失效的巨型组件。

它强调的规范：

- **组件原子化**:小而单一职责的 SFC,展示组件 vs 容器组件分离,过大立即拆。
- **逻辑抽 composable**:有状态/副作用逻辑抽成 `useX`,`setup` 保持声明式;禁巨型 composable。
- **props/emits 精确建模**:`defineProps<T>()` / `defineEmits<T>()`、discriminated union 表达变体、禁 `any`。
- **响应式正确性**(Vue 头号 bug 源):`ref` vs `reactive`、禁解构 `reactive`/props(丢响应式,用 `toRefs`)、派生值用 `computed` 而非 `watch` 回写。
- **状态最小化 + 单向数据流**:props 向下、事件向上、禁改 prop,跨组件共享用 Pinia。
- **watch 只做副作用**:并做清理;`v-for` 用稳定 key、禁 `v-if`+`v-for` 同元素。
- 附带「收尾前自查清单」和 `references/patterns.md`(composable 抽取、响应式陷阱、`defineModel`、Pinia store 结构等)。

适用场景：写任何 Vue 组件 / composable / 前端 UI 时自动引导;也适合 review / 重构现有组件。

### 8. `req-align` —— 模糊需求的工程化对齐

用于把一句话 / 模糊需求，在动手前对齐成结构化产物，沉淀工程约束来规避返工，并把架构决策沉淀成可被后续阶段回查的历史索引。

它做的事情：

- **定位需求所在层**：需求层 / SDD 层 / 架构层 / 执行层——只有需求层才做对齐，其他层转交对应 skill。
- **历史架构决策扫描**：澄清前先扫 `docs/req-align-history/index.md`，用关键词做简单包含匹配；命中才用 `AskUserQuestion` 问用户是否参考对应 per-run 目录的完整决策，把已决议边界当作既有上下文带入本次对齐——避免重新踩同一个坑或无声推翻既有决策。
- **最少澄清**：只问最高价值的 1-3 个问题（交付物 / 关键不变量 / 已知边界）。
- **对齐六要素**：目标、范围（✅ 支持 / ⛔ 暂不支持，显式边界必填）、优先级、**可观察的验收标准**（禁"要好 / 稳定 / 正常"这类不可观察词）、架构边界风险、下一阶段判定。
- **架构边界扫描**：数据流 / 时序事件流 / 跨服务调用 / 领域模型 / 外部 API 契约——只标记风险与建议验证阶段，未命中的边界也要写一行"未命中"证明扫过；命中历史决议的直接引用而非重判，要覆盖必须写理由。规避"需求正确、代码正确、但架构边界错误"的返工。
- **落盘为 per-run 目录**（与 `docs/exec-plan-*/` 同构）：`docs/req-align-<yyyy-mm-dd>-<slug>/` 下三份文件——`align.md`（六要素对齐）、`arch-risk.md`（边界扫描表 + append-only 决议记录，由后续阶段回填）、`acceptance.md`（`- [ ]` 人工验收勾选清单，首次落盘全未勾选是正常状态）。同时追加一行摘要到 `docs/req-align-history/index.md`（文件不存在则连表头一起创建）。**目录已存在时绝不覆盖**，改用 `-2`、`-3` 递增后缀。
- **产物自检**：`python3 scripts/check_alignment.py docs/req-align-<yyyy-mm-dd>-<slug>/` 校验三文件齐全性、六要素完整性、验收可观察性、checkbox 格式；退出码 `0` 全过 / `1` 有缺陷 / `2` 路径错误。脚本不校验 checkbox 是否已勾选、也不要求决议记录非空——那是后续阶段的事。

适用场景：拿到模糊 / 一句话需求、需求缺边界或验收标准、需求触碰系统边界（事件流 / SSE / 多 Agent / 外部 API 契约）需要在写代码前先识别风险、需要沉淀架构决策以防后期漂移、需要一份执行完成后可人工核对的验收清单时。

### 9. `req-align-v2` —— 需求对齐（稳定 ID 契约 + 边界沉淀 + 脚本闭环）

把模糊需求工程化对齐，产出带稳定 ID 的可观察验收标准、架构边界风险、机器契约与边界台账。

- **稳定 ID 硬契约**：验收写成 `- AC-1 (P0) 输入 X → 输出 Y`，风险写成 `RISK-N`，边界决策写成 `BND-N`。下游（SDD / 架构发现 / exec-plan）**只能引用，禁止重新编号**。
- **机器契约 `handoff.json`**：由 `align_state.py sync` 从三份 Markdown 派生（禁止手写），内含 `source_sha256` 指纹；下游读到契约后还会比对三份源文件原始字节，改了源文件没重跑 `sync` 会被拦下。
- **模块级边界台账 `boundaries.md`**：以**模块**为主键、一行一条决策、强制单句结论（脚本拒绝 >120 字符）。
- **双向失效标记**：`boundary_state.py supersede` 一条命令同时改台账两行 + 给旧 run 的 `arch-risk.md` 插失效横幅 + 更新时间线。
- **项目级踩坑库 `pitfalls.md`**：每条挂在一个 BND 上，同类 `count+1`；下次对齐命中该边界时由 `scan` 自动带出。与个人级 `~/.claude/lessons.md` 分工（后者存跨项目技术教训）。
- **脚本闭环，禁止手改**：`arch-risk.md` 的状态列、`acceptance.md` 的 checkbox、`boundaries.md` 的任何一行都只能由脚本改。`resolve-risk` 在同一次原子写里改状态列并追加决议段；`close-ac` 可用 `--run-cmd` 让脚本亲自执行验证命令（非零退出拒绝关闭并记录代码版本），也可用 `--manual --observer` 或裸 `--evidence`（自报文本，P0 收尾不予采信）。
- **两处人工闸门**：台账新增/变更、高危边界命中。闸门结果是写命令的**必填参数**（`--confirmed-by` / `--gate-outcome`），跳过闸门就写不进台账。
- **收尾门禁**：`check_alignment.py <run_dir> --strict-closure` 要求验收全勾选、P0 证据为脚本执行或人工观察且针对当前代码版本、无 `待验证` 遗留、并有 `record-review` 记录的 final 独立审核。
- **留存式可观测**：所有脚本在动作末尾追加一行 JSONL 到 `docs/.skill-metrics/runs.jsonl`（隐藏目录，随仓库提交）。**脚本写、LLM 从不读**，所以上下文成本为 0。

### 10. `execute-plan-plus-v2` —— 执行计划（上游摄取 + 每步增量闭环）

大型实现计划的可恢复分步执行。无上游时进入通用模式。

- **目录命名统一**：`docs/exec-plan-<yyyy-mm-dd>-<slug>/`，slug 继承上游。命名合规由 `update_step_state.py` 拒绝，不是散文要求。
- **Step 0 上游摄取**：扫 `docs/req-align-*/handoff.json`，写 `upstream.json`（`/compact` 后靠它恢复链接）。未命中则进入通用模式，全部上游相关校验自动跳过。
- **`step.json` 带 `covers`**：每个 step 声明它服务哪些 `AC-N`；`audit_coverage.py` 在执行前强制 100% AC 覆盖，并校验 `requirements.md` 的 `Covers:` 与之一致。
- **每步增量回写**：`complate` 前置校验该 step 覆盖的 AC 已在上游闭环，否则拒绝并打印应执行的 `close-ac` 命令。
- **`block` 强制表态**：必须给 `--pitfall PIT-N` 或 `--no-pitfall REASON`。
- **收尾门禁**：`final_gate.py <plan_dir> --req-align-scripts <dir>` 一键跑步骤完成度、AC 覆盖审计、上游 `--strict-closure` 与历史同步；未过则报「未完成」。

## 目录结构

```
skill/
├── README.md
├── INSTALL_FOR_LLM.md          # 给 LLM 看的安装指令
├── execute-plan-plus/
│   ├── SKILL.md
│   ├── scripts/
│   │   └── update_step_state.py
│   ├── references/
│   └── evals/
│       └── evals.json
├── orchestrate-plan/
│   ├── SKILL.md
│   ├── scripts/
│   │   └── run_state.py
│   ├── references/
│   │   └── dispatch-prompts.md
│   └── evals/
│       └── evals.json
├── use-worktree/
│   ├── SKILL.md
│   └── scripts/
│       └── worktree_manager.py
├── req-align/
│   ├── SKILL.md
│   ├── agents/
│   │   └── openai.yaml
│   ├── scripts/
│   │   └── check_alignment.py
│   └── references/
│       ├── templates.md
│       └── risk-patterns.md
├── req-align-v2/
│   ├── SKILL.md
│   ├── agents/
│   │   └── openai.yaml
│   ├── scripts/
│   │   ├── _artifacts.py            # 共享解析与原子写（避免正则三处漂移）
│   │   ├── align_state.py           # run 内写操作唯一入口
│   │   ├── boundary_state.py        # 跨 run 沉淀：台账 / 踩坑库 / 时间线
│   │   ├── check_alignment.py       # 自检 + --strict-closure 收尾门禁
│   │   └── metrics.py               # 留存埋点（脚本写，LLM 不读）
│   ├── references/
│   │   ├── templates.md
│   │   ├── risk-patterns.md
│   │   └── downstream-contract.md   # 四阶段命名 + 中间层目录规范 + ID 透传
│   ├── tests/
│   └── evals/
│       └── evals.json
├── execute-plan-plus-v2/
│   ├── SKILL.md
│   ├── scripts/
│   │   ├── update_step_state.py     # + slug 校验 / covers 闭环门禁 / block 表态
│   │   ├── audit_coverage.py        # 执行前 AC 覆盖门禁
│   │   ├── final_gate.py            # 一键收尾门禁（步骤/覆盖/严格闭环/历史同步）
│   │   └── metrics.py
│   ├── tests/
│   └── evals/
│       └── evals.json
├── python-engineering/
│   ├── SKILL.md
│   └── references/
│       └── patterns.md
├── react-engineering/
│   ├── SKILL.md
│   └── references/
│       └── patterns.md
├── nodejs-engineering/
│   ├── SKILL.md
│   └── references/
│       └── patterns.md
└── vue3-engineering/
    ├── SKILL.md
    └── references/
        └── patterns.md
```

## 安装方式

见 [INSTALL_FOR_LLM.md](./INSTALL_FOR_LLM.md)，里面写了给 LLM / Claude Code 直接照做的一键安装指令。

如果你想手动装：

```bash
# 把整个 skill 目录 copy 到 Claude Code 的用户级 skills 目录下
mkdir -p ~/.claude/skills
cp -R execute-plan-plus ~/.claude/skills/
cp -R orchestrate-plan ~/.claude/skills/
cp -R use-worktree ~/.claude/skills/
```

安装完之后重启 Claude Code（或者开一个新会话）即可看到这些 skill。

## 使用方式

安装后，Claude Code 会根据 SKILL.md 中的 `description` 自动决定何时触发；你也可以显式调用：

- `/execute-plan-plus` —— 开始一个新的大型计划执行流程，或恢复已有的 `docs/exec-plan-*/`。
- `/orchestrate-plan` —— 把一份已批准的 plan 交给自主编排 loop 执行（主 agent 只派发、子 agent 执行+验收、失败中止出报告、最后整体 review + codebase 验证），或恢复已有的 `docs/orchestrate-plan-*/`。
- `/use-worktree` —— 让 Claude 帮你创建 / 列出 / 删除 worktree。
- `/python-engineering` —— 让 Claude 按 Python 工程规范写 / 重构 / review 代码。
- `/react-engineering` —— 让 Claude 按 React 工程规范写 / 重构 / review 组件。
- `/nodejs-engineering` —— 让 Claude 按 Node.js 工程规范写 / 重构 / review 后端代码。
- `/vue3-engineering` —— 让 Claude 按 Vue 3 工程规范写 / 重构 / review 组件。
- `/req-align` —— 把模糊需求工程化对齐成目标 / 边界 / 验收标准 / 架构风险，落盘为 `docs/req-align-<date>-<slug>/` + 历史索引，并判定下一阶段。
- `/req-align-v2` —— 同上，外加稳定 ID（AC-N / RISK-N / BND-N）、机器契约 `handoff.json`、模块级边界台账与踩坑库、脚本强制的闭环回写与双向失效标记、两处人工闸门。
- `/execute-plan-plus-v2` —— 摄取上游 `handoff.json`，产出目录名继承上游 slug，每个 step 声明 `covers` 并在 `complate` 前把覆盖的验收就地闭环；无上游时进入通用模式。

## 让工程规范 skill「每次都生效」

`python-engineering` / `react-engineering` / `nodejs-engineering` / `vue3-engineering` 这类规范 skill，靠 `description` **语义匹配自动触发**——但这是**概率触发**：Claude 随手写点代码时，不一定每次都主动加载 skill。

如果你希望它在某个项目里**每次写代码都遵循**，在那个项目根目录的 `CLAUDE.md` 里加一小段常驻指针（这段是给用 skill 的项目用的，不是放在本仓库）：

```markdown
## 工程规范

- 写 / 重构 **Python** 时，遵循 `python-engineering` skill：类型建模优先、函数单一职责、完整类型标注、显式报错。
- 写 / 重构 **React** 时，遵循 `react-engineering` skill：组件原子化、逻辑抽 custom hook、禁巨型 hook/组件、状态最小化。
- 写 / 重构 **Node.js** 后端时，遵循 `nodejs-engineering` skill：异步正确性、分层架构、边界校验、错误传播、配置与安全。
- 写 / 重构 **Vue 3** 时，遵循 `vue3-engineering` skill：组件原子化、逻辑抽 composable、响应式正确性(禁解构丢响应式)、单向数据流。
- 发现函数 / 组件变大，或出现裸 dict / any、floating promise、prop 被直接修改，立即按对应 skill 拆分、建类型、修正。
```

这样 `CLAUDE.md` 常驻上下文里**必然被看到**，负责「提醒去用 skill」；skill 本身承载「具体怎么写」的详细规则和正反例。两者配合，才能既可靠触发、又不把上下文塞爆。

> 想要**硬约束**（格式 / 复杂度 / 依赖必然被拦）而不只是引导，需要额外配 `PostToolUse` hook 跑 linter（ruff / mypy / eslint）。本仓库当前只提供 skill 引导层，未包含 hook。

## License

个人使用，随便拿。
