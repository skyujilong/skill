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
