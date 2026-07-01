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

### 2. `use-worktree` —— Git Worktree 并行开发管理

用于快速创建/列出/删除 git worktree，让你可以在多个分支上**同时并行开发**而无需来回切换分支。

它做的事情：

- 在**同级目录**下按 `{project-name}-worktree-{branch-name}` 命名创建 worktree。
- 自动识别项目类型并安装依赖：Python (`uv sync`)、Node.js (`pnpm install`)、Rust (`cargo`)、Go (`go mod`)、Java (`mvn`)，也支持 `frontend/` + `backend/` monorepo。
- `list` 时自动检查每个 worktree 是否 dirty / locked，并输出结构化结果。
- `delete` 前会检查未提交改动 + 是否已合并到主分支，需要用户明确确认。
- 所有操作都走 `scripts/worktree_manager.py`，避免边界情况（`node_modules`、`.venv`、缓存目录等）导致的删除失败。

适用场景：需要同时跑多个 feature/fix 分支、或者想在不打断当前工作的前提下临时切到另一个分支排查问题。

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
└── use-worktree/
    ├── SKILL.md
    └── scripts/
        └── worktree_manager.py
```

## 安装方式

见 [INSTALL_FOR_LLM.md](./INSTALL_FOR_LLM.md)，里面写了给 LLM / Claude Code 直接照做的一键安装指令。

如果你想手动装：

```bash
# 把整个 skill 目录 copy 到 Claude Code 的用户级 skills 目录下
mkdir -p ~/.claude/skills
cp -R execute-plan-plus ~/.claude/skills/
cp -R use-worktree ~/.claude/skills/
```

安装完之后重启 Claude Code（或者开一个新会话）即可看到这两个 skill。

## 使用方式

安装后，Claude Code 会根据 SKILL.md 中的 `description` 自动决定何时触发；你也可以显式调用：

- `/execute-plan-plus` —— 开始一个新的大型计划执行流程，或恢复已有的 `docs/exec-plan-*/`。
- `/use-worktree` —— 让 Claude 帮你创建 / 列出 / 删除 worktree。

## License

个人使用，随便拿。
