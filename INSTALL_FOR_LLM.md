# INSTALL_FOR_LLM.md

> 这份文档是**写给 LLM（例如 Claude Code / Claude / 其他 coding agent）看的**。
> 当用户把这个仓库丢给你，并说"帮我把这些 skill 装上"时，请**严格按照下面的步骤执行**，不要自行发挥。

## 目标

把本仓库中的所有 skill 目录（每个 skill 目录下都包含一个 `SKILL.md`）复制到 Claude Code 的**用户级 skills 目录**：

```
~/.claude/skills/
```

安装后，Claude Code 会自动加载这些 skill；用户下次开启新会话时即可通过 `/<skill-name>` 触发，或者由 SKILL.md 中 `description` 字段的语义匹配自动触发。

## 前置条件

- 用户机器上已经安装了 Claude Code。
- 用户机器上存在或可以创建目录 `~/.claude/skills/`。
- 你当前的工作目录是本仓库根目录（存在 `README.md` 和若干 skill 子目录，例如 `execute-plan-plus/`、`use-worktree/`）。

## 执行步骤

### Step 1. 识别本仓库中所有 skill

Skill 的定义是：**根目录下、包含 `SKILL.md` 的一级子目录**。

用如下命令列出所有 skill：

```bash
find . -mindepth 2 -maxdepth 2 -type f -name SKILL.md -exec dirname {} \;
```

对于本仓库当前的内容，预期输出应包含：

- `./execute-plan-plus`
- `./use-worktree`

（未来如果仓库增加了新 skill，也会自动出现在这里。**不要硬编码 skill 名字**。）

### Step 2. 确认目标目录存在

```bash
mkdir -p ~/.claude/skills
```

### Step 3. 检查是否会覆盖已有 skill

对每一个待安装的 skill，检查目标位置是否已存在：

```bash
ls ~/.claude/skills/<skill-name>
```

- 如果不存在：直接进入 Step 4 复制。
- 如果**已存在**：**必须先向用户确认**是覆盖、跳过、还是先备份到 `~/.claude/skills/<skill-name>.bak-<timestamp>`。不要静默覆盖用户已有的 skill。

### Step 4. 复制 skill 目录

对每一个待安装的 skill，执行：

```bash
cp -R <skill-name> ~/.claude/skills/
```

例如：

```bash
cp -R execute-plan-plus ~/.claude/skills/
cp -R use-worktree ~/.claude/skills/
```

不要只复制 `SKILL.md`——`scripts/`、`references/`、`evals/` 等子目录都是 skill 运行时的一部分，必须整目录复制。

### Step 5. 验证安装

```bash
ls -la ~/.claude/skills/
```

对每个刚复制过去的 skill，再确认 `SKILL.md` 和 `scripts/` 都在：

```bash
ls -la ~/.claude/skills/<skill-name>/
```

### Step 6. 告诉用户下一步做什么

安装完成后向用户明确说明：

1. 需要**重启 Claude Code** 或者**开一个新的会话**，新 skill 才会被加载。
2. 加载之后可以通过 `/<skill-name>` 显式触发，例如 `/execute-plan-plus`、`/use-worktree`。
3. 也可以直接用自然语言描述场景，Claude Code 会根据 SKILL.md 里的 `description` 自动决定要不要触发。

## 不要做的事

- ❌ 不要把 skill 装到项目级目录（`.claude/skills/`），除非用户明确要求"只在当前项目生效"。默认装到用户级 `~/.claude/skills/`。
- ❌ 不要修改 skill 内部的 `SKILL.md`、脚本内容或 frontmatter。安装 = 原样搬运。
- ❌ 不要静默覆盖已存在的同名 skill。
- ❌ 不要遗漏 `scripts/` 等子目录；只 copy `SKILL.md` 会让 skill 运行时报错。
- ❌ 不要用 `mv` 代替 `cp -R`——用户可能还想继续用这个仓库。

## 一键脚本参考（可选）

如果你想一次装完，可以直接跑这段：

```bash
set -e
mkdir -p ~/.claude/skills
for skill_dir in $(find . -mindepth 2 -maxdepth 2 -type f -name SKILL.md -exec dirname {} \;); do
  name=$(basename "$skill_dir")
  target="$HOME/.claude/skills/$name"
  if [ -e "$target" ]; then
    echo "SKIP: $name already exists at $target (ask user before overwriting)"
    continue
  fi
  cp -R "$skill_dir" "$target"
  echo "INSTALLED: $name -> $target"
done
```

执行完记得提醒用户重启 Claude Code。
