# 模板与清单（req-align）

## 1. 落盘产物模板

产物目录：`docs/req-align-<yyyy-mm-dd>-<slug>/`（slug 用小写字母 / 数字 / 连字符）。
目录已存在时不覆盖，改用 `-2`、`-3` 递增后缀。

```text
docs/
├── req-align-history/
│   └── index.md        # 跨需求的架构决策索引（只存摘要 + 链接）
└── req-align-<yyyy-mm-dd>-<slug>/
    ├── align.md        # 六要素对齐文档
    ├── arch-risk.md    # 边界风险扫描 + 决议记录（append-only）
    └── acceptance.md   # 人工验收勾选清单
```

### 1a. `align.md`

```markdown
# 需求对齐：<标题>

日期: <yyyy-mm-dd> | 状态: 草稿/已确认 | 来源: <一句话>

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

- 输入 <A> → 输出 <B>（P0）
- 输入 <C> → 行为 <D> 持续 <E>（P1）

## 🧱 架构边界风险

见 `arch-risk.md`（风险扫描表与决议记录）。

## ➡️ 下一阶段

判定: <直接推进 / 需 SDD 深化 / 先做架构发现>
去向: <架构发现 / SDD 规格 / 执行计划>
沿用的历史决策: <链接到历史 arch-risk.md 的决议，或"无">
```

### 1b. `arch-risk.md`

两个二级标题**必须原样保留**（自检脚本按标题定位）；决议段用**三级标题**挂在「决议记录」之下。

```markdown
# 架构边界风险与决议：<标题>

## 🧱 边界风险扫描

| 边界 | 风险 | 建议验证阶段 | 状态 |
| --- | --- | --- | --- |
| 事件流时序 | 谁负责解包 / 谁负责流转未定 | 架构发现时用 trace_path 查调用链 | 待验证 |
| 持久化领域模型 | 未命中 | — | 未命中 |

## 📌 决议记录

<!-- append-only：架构发现 / 实现阶段验证完一条边界后追加一段。首次落盘时本区块为空是正常的。 -->

### <yyyy-mm-dd HH:MM> — <边界名> 决议
- 决议: ...
- 理由: ...
- 影响: ...
```

规则：

- 逐项过完 `risk-patterns.md` §2 清单后，**未命中的边界也要写一行**（写"未命中"），证明扫过而非漏扫。
- 一条边界被验证 / 决议后：追加 `###` 决议段，并把扫描表该行「状态」改为 `已决议`。
- 决议段格式对齐 `execute-plan-plus` 的 `decisions.md`（ADR-lite）：决议 / 理由 / 影响三件套，append-only，不改写历史。

### 1c. `acceptance.md`

```markdown
# 验收清单：<标题>

来源: `align.md` 的「✅ 验收标准」 | 执行完成后按下列步骤人工核对，全部勾选才算验收通过。

- [ ] 输入 <A> → 输出 <B>（P0）
- [ ] 输入 <C> → 行为 <D> 持续 <E>（P1）

## 未通过记录

<!-- 核对不通过时追加：现象 / 期望 / 关联的 arch-risk 决议 -->
```

规则：条目必须是 `- [ ]` 勾选格式且逐条可观察（见 §4）。首次落盘时全部未勾选是正常状态。

### 1d. `req-align-history/index.md`

```markdown
# 架构决策历史索引

一行一条已确认的架构决策，只存摘要与链接；完整内容在各自 per-run 目录的 `arch-risk.md` 里。

| 日期 | 模块/slug | 决策摘要 | 状态 | 链接 |
| --- | --- | --- | --- | --- |
| 2026-08-04 | payment-sse | SSE 消息解包边界归 gateway 层 | 已确认 | ../req-align-2026-08-04-payment-sse/arch-risk.md |
```

每次对齐落盘时追加一行（文件不存在则连表头一起创建）。

## 2. 澄清问题清单

按价值排序，只挑 1-3 个问，能靠上下文推断就不问：

- **交付物**：系统 / 功能 / 修复 / 调研？可接受的最小可用版本是什么？
- **不变量**：哪个环节坏了最致命？允许什么程度的不完美？
- **边界**：有没有明确不做的事？依赖哪些现有系统 / 数据 / API？
- **验收**：你用什么方式判断"做完了"？能举一个输入输出例子吗？
- **风险**：是否牵扯实时性 / 顺序 / 一致性 / 跨系统？同类需求之前是否返工过？

「是否参考历史架构决策」不占这 1-3 个额度——它由历史扫描步骤自动触发（见 SKILL.md Step 2）。

## 3. SDD 模板（仅当判定"需 SDD 深化"时使用）

把自然语言验收改写为 Given/When/Then 规格，让"机器和测试可验证"：

```text
<Feature> Specification:

Given:
  <前置条件，如 same character_id>
When:
  <触发行为，如 generating different scenes>
Then:
  must preserve: <必保属性列表>

Allowed variation:
  <允许的变化范围，如 emotion / pose / lighting>
```

示例（角色一致性）：

```text
Character Consistency Specification:
Given: same character_id
When: generating different scenes
Then: must preserve face features / hair style / costume / age appearance
Allowed variation: emotion / pose / lighting
```

## 4. 可观察性检查表

判断规则：一条验收能否被一个测试断言？不能 = 不可观察 = 必须改写。
同时适用于 `align.md` 的「✅ 验收标准」与 `acceptance.md` 的勾选条目。

| 不可观察 | 可观察改写 |
| --- | --- |
| 角色一致性要好 | 同 character_id 跨场景：五官 / 发型 / 服饰 / 年龄感不变，仅表情 / 姿势 / 光照可变 |
| 系统要稳定 | 1000 次请求错误率 < 0.1%，无崩溃，P95 延迟 < 2s |
| 输出正常 | 输入 story → 输出 10 个分镜，每个含 镜头 / 角色 / 动作 / Prompt |
| 体验流畅 | 用户发送消息后 3s 内首 token 到达，流式过程中无中断回退 |

高频不可观察词：要好 / 稳定 / 正常 / 流畅 / 自然 / 合理 / 高效 / 完善 / 可靠 / 好看 / 好用。
