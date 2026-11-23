# 规格结构指南（sdd-v2）

目录形态以 req-align-v2 的 `references/downstream-contract.md` §2 为准。

```text
docs/sdd-<yyyy-mm-dd>-<slug>/
├── README.md             # 必须
├── 01-overview.md        # 必须：完整需求文档
├── acceptance-matrix.md  # 必须
├── data-model.md         # 可选
└── api-contracts.md      # 可选
```

## README.md

入口：一句话概述、阅读顺序（01 -> 矩阵 -> 可选文件）、**上游 run 目录路径**（写目录名，检查器会找）、状态（草稿/已审阅/已登记）。

## 01-overview.md（完整需求文档）

用二级标题（检查器按关键词匹配）：

| 章节 | 内容要求 |
| --- | --- |
| 背景与目标 | 为什么做、做成什么样 |
| 范围 | 支持 / 不支持，继承自 align.md，不另起炉灶 |
| 角色与用户场景 | 谁在什么情境下做什么 |
| 功能需求 | 按 AC 分组，AC-N 与 align.md 文字**逐字引用**，其下补充说明 |
| 非功能需求 | 性能、安全、多租户、可观测性、兼容性；每条写成可测（数字/断言），不写"要快" |
| 接口与数据概述 | 关键接口/实体的概览；细节放可选文件 |
| 错误与边界场景 | 失败、越权、超时、空输入等及预期行为 |
| 假设与开放问题 | 每条带负责人（`负责人:`/`owner:`/`@`），否则 WARN |
| 与架构发现的关系 | 仍为 `待验证` 的 RISK-N 列表——它们阻塞实现 |

## acceptance-matrix.md

表头固定：`| AC | 规格（Given/When/Then） | 覆盖模块 | 备注 |`

- 每个上游 AC 恰好一行；id 不改、不增、不重排。子用例放在同一行，用 `<br>` 分隔。
- 规格含 Given、When、Then（或 给定/当/则）；一条规格对应一个可断言的结果。
- 覆盖模块写真实模块/包名，不留占位（TBD/待定/略/N/A）。
- P0 行必须有失败或边界例（越权、超时、空输入、错误码……），写在规格的第二个子用例或备注里。
- 不要把表格放进围栏代码块，检查器会忽略它。

## 示例（功能：导出用户列表为 CSV）

上游：AC-1 (P0) 管理员导出本租户用户 → 下载 CSV；AC-2 (P1) 导出文件名含日期。

README.md：

```markdown
# SDD：用户列表导出
上游: req-align-2026-09-02-user-export
阅读顺序: 01-overview.md -> acceptance-matrix.md
状态: 草稿
```

01-overview.md（节选）：

```markdown
## 1. 背景与目标
运营需要离线核对用户，目标是一键导出。
## 2. 范围
支持：CSV 导出。不支持：Excel、跨租户导出。
## 3. 功能需求
- AC-1 (P0) 管理员导出本租户用户 → 下载 CSV
- AC-2 (P1) 导出文件名含日期
## 4. 非功能需求
1 万行导出 P95 < 5s；仅返回本租户数据。
## 5. 错误与边界场景
非管理员 403；无数据返回仅含表头的 CSV。
## 6. 假设与开放问题
- 单次最多 5 万行是否足够？负责人: @产品
```

acceptance-matrix.md：

```markdown
| AC | 规格（Given/When/Then） | 覆盖模块 | 备注 |
| --- | --- | --- | --- |
| AC-1 | Given 租户 A 管理员 / When 请求导出 / Then 200 且 CSV 仅含租户 A 用户<br>Given 非管理员 / When 请求导出 / Then 403 | api/export | 越权拒绝 |
| AC-2 | Given 2026-09-02 / When 导出 / Then 文件名为 users-20260902.csv | api/export | |
```
