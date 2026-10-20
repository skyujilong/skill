#!/usr/bin/env python3
"""req-align-v2 跨 run 沉淀入口：模块级边界台账、踩坑库、run 时间线。

用法:
  python3 scripts/boundary_state.py add --run <run_dir> --module M --statement T \
      --confirmed-by human --gate-outcome adopted [--from-risk RISK-N]
  python3 scripts/boundary_state.py supersede BND-4 --by <run_dir> --new-statement T \
      --reason T --confirmed-by human --gate-outcome adopted
  python3 scripts/boundary_state.py scan --keywords 服务,租户 [--history-dir PATH]
  python3 scripts/boundary_state.py pitfall-add --boundary BND-3 --phenomenon T \
      --root-cause T --guard T [--history-dir PATH]
  python3 scripts/boundary_state.py history-sync <run_dir>

两条设计要点：

1. **覆盖必须双向可见。** 如果只在台账里标记覆盖、不在旧 run 里留横幅，旧 run 里
   零标记，仍自称生效——下次扫描会同时命中失效与生效两条。`supersede` 因此在一条命令里
   同时改台账两行、给旧 run 的 arch-risk.md 插失效横幅、更新时间线。
2. **`scan` 只输出命中行。** 台账会随项目线性增长，若让调用方读整份文件，上下文成本
   同步增长。这里在脚本侧过滤，调用方物理上拿不到全量。

`--confirmed-by` / `--gate-outcome` 是人工闸门的落点：脚本拒绝缺失，
所以跳过闸门就写不进台账（不依赖调用方自觉上报"我问过了"）。

退出码: 0 成功 / 1 校验失败 / 2 参数或路径错误。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import metrics  # noqa: E402
from _artifacts import (  # noqa: E402
    ARCH_RISK_FILE,
    BOUNDARIES_FILE,
    HISTORY_DIRNAME,
    INDEX_FILE,
    PITFALLS_FILE,
    ArtifactError,
    atomic_write,
    build_row,
    find_table,
    level2_span,
    load_handoff,
    next_id,
    parse_ledger,
    parse_pitfalls,
    parse_risk_table,
    parse_run_dirname,
    read_text,
    require_dir,
    split_row,
)

SKILL = "req-align-v2"

BOUNDARIES_HEADER = """# 架构边界台账

一行一条决策，以模块为主键。生命周期受控值：生效 / 已被覆盖。
只允许 `boundary_state.py` 写入；覆盖时脚本会同步在旧 run 的 arch-risk.md 插入失效横幅。

| ID | 模块 | 边界结论（一句话） | 生命周期 | 来源 run | 被谁覆盖 |
| --- | --- | --- | --- | --- | --- |
"""

PITFALLS_HEADER = """# 项目级踩坑库

每条挂在一个 BND 上；下次对齐命中该边界时由 `boundary_state.py scan` 自动带出。
与个人级 `~/.claude/lessons.md` 分工：个人级存跨项目技术教训，本文件存本项目边界上的坑。

| ID | 关联边界 | 现象 | 根因 | 防护规则 | count |
| --- | --- | --- | --- | --- | --- |
"""

INDEX_HEADER = """# 需求对齐 run 时间线

台账（boundaries.md）回答「边界现在是什么」，本文件只回答「什么时候做过哪些 run」。
「验收闭环」「风险决议」由 `boundary_state.py history-sync` 重算，不手填。

| 日期 | slug | 下一阶段 | 验收闭环 | 风险决议 | 链接 |
| --- | --- | --- | --- | --- | --- |
"""


# --------------------------------------------------------------------- helpers


def resolve_history(run_dir: Path = None, explicit: str = None, create: bool = False) -> Path:
    if explicit:
        path = Path(explicit)
    elif run_dir is not None:
        path = run_dir.resolve().parent / HISTORY_DIRNAME
    else:
        path = Path.cwd() / "docs" / HISTORY_DIRNAME
    if not path.is_dir():
        if not create:
            raise ArtifactError(
                f"沉淀目录不存在: {path}（用 --history-dir 指定，或先跑一次 add 创建）"
            )
        path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_ledger(path: Path, header: str) -> None:
    if not path.is_file():
        atomic_write(path, header)


def append_table_row(path: Path, header: str, cells) -> None:
    ensure_ledger(path, header)
    lines = read_text(path).splitlines()
    table = find_table(lines)
    if table is None:
        raise ArtifactError(f"{path} 里找不到表格，格式已损坏")
    insert_at = (table.row_indices[-1] + 1) if table.row_indices else table.separator_index + 1
    lines.insert(insert_at, build_row(cells))
    atomic_write(path, "\n".join(lines) + "\n")


def replace_table_row(path: Path, row_index: int, cells) -> None:
    lines = read_text(path).splitlines()
    lines[row_index] = build_row(cells)
    atomic_write(path, "\n".join(lines) + "\n")


def run_label(run_dir: Path) -> str:
    """把 req-align-2026-09-02-foo 记为 2026-09-02-foo（台账里更紧凑）。"""
    date, slug = parse_run_dirname(run_dir)
    return f"{date}-{slug}"


def locate_run(history_dir: Path, label: str) -> Path:
    candidate = history_dir.resolve().parent / f"req-align-{label}"
    if not candidate.is_dir():
        raise ArtifactError(
            f"找不到来源 run 目录 {candidate}：无法写入失效横幅。"
            "被覆盖的旧决议若不打标记，下次扫描会把它当成仍然生效的决议。"
        )
    return candidate


def preflight_banner_target(run_dir: Path) -> None:
    """写台账前确认失效横幅一定写得进去（arch-risk.md 存在且有「决议记录」小节）。"""
    path = run_dir / ARCH_RISK_FILE
    if not path.is_file():
        raise ArtifactError(f"{path} 不存在，无法写入失效横幅")
    if level2_span(read_text(path).splitlines(), "决议记录") is None:
        raise ArtifactError(f"{path} 缺「## 📌 决议记录」小节，无法写入失效横幅")


def insert_superseded_banner(run_dir: Path, old_id: str, new_id: str,
                             by_label: str, reason: str) -> None:
    """在旧 run 的 arch-risk.md「决议记录」小节顶部插入失效横幅。"""
    preflight_banner_target(run_dir)
    path = run_dir / ARCH_RISK_FILE
    lines = read_text(path).splitlines()
    span = level2_span(lines, "决议记录")
    banner = f"> ⚠️ 已被 {new_id}（{by_label}）覆盖：{reason}（原 {old_id}）"
    if banner in lines:
        return
    lines.insert(span[0], banner)
    lines.insert(span[0] + 1, "")
    atomic_write(path, "\n".join(lines) + "\n")


def render_hits(boundaries, pitfalls) -> str:
    out = []
    for boundary in boundaries:
        marker = "⚠️ 已被覆盖" if boundary.lifecycle == "已被覆盖" else "生效"
        out.append(f"[{boundary.id}] {boundary.module} | {boundary.statement} "
                   f"| {marker} | 来源 {boundary.source_run}"
                   + (f" | 被 {boundary.superseded_by} 覆盖" if boundary.superseded_by not in ("", "—") else ""))
        for pit in pitfalls:
            if pit.boundary == boundary.id:
                out.append(f"    ↳ [{pit.id}] 坑x{pit.count}: {pit.phenomenon} "
                           f"→ 防护: {pit.guard}")
    return "\n".join(out)


# -------------------------------------------------------------------- commands


def cmd_add(args) -> int:
    run_dir = require_dir(args.run)
    if not args.statement.strip():
        raise ArtifactError("--statement 不能为空")
    if "\n" in args.statement or len(args.statement) > 120:
        raise ArtifactError("--statement 必须是一句话（≤120 字符）：长句会让台账无法检索")
    if args.from_risk:
        # 先确认 risk 存在再碰台账——否则台账已加 BND 但关联失败，留下无主 BND
        _ensure_risk_exists(run_dir, args.from_risk)
    history = resolve_history(run_dir, args.history_dir, create=True)
    ledger_path = history / BOUNDARIES_FILE
    ensure_ledger(ledger_path, BOUNDARIES_HEADER)
    existing = parse_ledger(ledger_path)
    new_id = next_id([b.id for b in existing], "BND")
    label = run_label(run_dir)

    append_table_row(ledger_path, BOUNDARIES_HEADER,
                     [new_id, args.module.strip(), args.statement.strip(),
                      "生效", label, "—"])

    if args.from_risk:
        link_risk_to_boundary(run_dir, args.from_risk, new_id)

    metrics.emit(SKILL, "boundary_added", run=run_dir, bnd_id=new_id,
                 confirmed_by=args.confirmed_by, gate_outcome=args.gate_outcome)
    print(f"added {new_id}: {args.module.strip()} | {args.statement.strip()}")
    return 0


def link_risk_to_boundary(run_dir: Path, risk_id: str, bnd_id: str) -> None:
    path = run_dir / ARCH_RISK_FILE
    text = read_text(path)
    lines = text.splitlines()
    risk = next((r for r in parse_risk_table(text) if r.id == risk_id), None)
    if risk is None:
        raise ArtifactError(f"{run_dir} 的扫描表中找不到 {risk_id}")
    cells = split_row(lines[risk.row_index])
    cells[3] = bnd_id
    lines[risk.row_index] = build_row(cells)
    atomic_write(path, "\n".join(lines) + "\n")


def _ensure_risk_exists(run_dir: Path, risk_id: str) -> None:
    """写台账前预检查 risk 存在，避免留下无主 BND。"""
    path = run_dir / ARCH_RISK_FILE
    risks = parse_risk_table(read_text(path))
    if not any(r.id == risk_id for r in risks):
        raise ArtifactError(f"{run_dir} 的扫描表中找不到 {risk_id}")


def cmd_supersede(args) -> int:
    by_dir = require_dir(args.by)
    if not args.new_statement.strip() or not args.reason.strip():
        raise ArtifactError("--new-statement 与 --reason 都不能为空")
    history = resolve_history(by_dir, args.history_dir)
    ledger_path = history / BOUNDARIES_FILE
    existing = parse_ledger(ledger_path)
    old = next((b for b in existing if b.id == args.bnd_id), None)
    if old is None:
        raise ArtifactError(f"台账里找不到 {args.bnd_id}")
    if old.lifecycle != "生效":
        raise ArtifactError(f"{args.bnd_id} 生命周期为「{old.lifecycle}」，不能再次覆盖")

    new_id = next_id([b.id for b in existing], "BND")
    label = run_label(by_dir)
    # 先确认旧 run 目录与 arch-risk.md 都存在再动台账——否则台账已改但横幅写不进去
    source_run_dir = locate_run(history, old.source_run)
    if not (source_run_dir / ARCH_RISK_FILE).is_file():
        raise ArtifactError(
            f"{source_run_dir / ARCH_RISK_FILE} 不存在，无法写入失效横幅。"
            "被覆盖的旧决议若不打标记，下次扫描会把它当成仍然生效的决议。"
        )
    preflight_banner_target(source_run_dir)
    # 1) 新增生效行  2) 旧行标记已被覆盖  3) 旧 run 插失效横幅 —— 一条命令内完成，
    # 任一步失败则台账恢复原字节（全有或全无）
    ledger_before = ledger_path.read_bytes().decode("utf-8")
    try:
        append_table_row(ledger_path, BOUNDARIES_HEADER,
                         [new_id, old.module, args.new_statement.strip(), "生效", label, "—"])
        refreshed = parse_ledger(ledger_path)
        old_row = next(b for b in refreshed if b.id == args.bnd_id)
        replace_table_row(ledger_path, old_row.row_index,
                          [old.id, old.module, old.statement, "已被覆盖",
                           old.source_run, new_id])
        insert_superseded_banner(source_run_dir, old.id, new_id, label, args.reason.strip())
    except Exception:
        atomic_write(ledger_path, ledger_before)
        raise

    metrics.emit(SKILL, "boundary_superseded", run=by_dir, bnd_id=args.bnd_id,
                 new_bnd_id=new_id, confirmed_by=args.confirmed_by,
                 gate_outcome=args.gate_outcome)
    print(f"superseded {args.bnd_id} -> {new_id}；已在 {source_run_dir.name} 插入失效横幅")
    return 0


def cmd_scan(args) -> int:
    history = resolve_history(None, args.history_dir)
    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    if not keywords:
        raise ArtifactError("--keywords 不能为空")
    boundaries = parse_ledger(history / BOUNDARIES_FILE)
    pitfalls = parse_pitfalls(history / PITFALLS_FILE)
    hits = [b for b in boundaries
            if any(k in b.module or k in b.statement for k in keywords)]
    if not hits:
        print("no-hit")
        return 0
    hit_ids = {b.id for b in hits}
    surfaced = [p for p in pitfalls if p.boundary in hit_ids]
    print(render_hits(hits, surfaced))
    for pit in surfaced:
        metrics.emit(SKILL, "pitfall_surfaced", run=None, pit_id=pit.id,
                     bnd_id=pit.boundary, count=pit.count)
    return 0


def cmd_pitfall_add(args) -> int:
    history = resolve_history(None, args.history_dir, create=True)
    path = history / PITFALLS_FILE
    ensure_ledger(path, PITFALLS_HEADER)
    pitfalls = parse_pitfalls(path)
    phenomenon = args.phenomenon.strip()
    guard = args.guard.strip()
    if not phenomenon or not guard:
        raise ArtifactError("--phenomenon 与 --guard 都不能为空")
    # 同类判定：同一边界上现象或防护规则重复 → count+1，避免踩坑库无限膨胀
    same = next((p for p in pitfalls
                 if p.boundary == args.boundary
                 and (p.phenomenon == phenomenon or p.guard == guard)), None)
    if same is not None:
        replace_table_row(path, same.row_index,
                          [same.id, same.boundary, same.phenomenon, same.root_cause,
                           same.guard, str(same.count + 1)])
        metrics.emit(SKILL, "pitfall_added", run=None, pit_id=same.id,
                     bnd_id=same.boundary, count=same.count + 1)
        print(f"merged {same.id}: count {same.count} -> {same.count + 1}")
        return 0
    new_id = next_id([p.id for p in pitfalls], "PIT")
    append_table_row(path, PITFALLS_HEADER,
                     [new_id, args.boundary, phenomenon, args.root_cause.strip(),
                      guard, "1"])
    metrics.emit(SKILL, "pitfall_added", run=None, pit_id=new_id,
                 bnd_id=args.boundary, count=1)
    print(f"added {new_id} on {args.boundary}")
    return 0


def cmd_history_sync(args) -> int:
    run_dir = require_dir(args.run_dir)
    history = resolve_history(run_dir, args.history_dir, create=True)
    path = history / INDEX_FILE
    ensure_ledger(path, INDEX_HEADER)
    data = load_handoff(run_dir)
    acceptance = data.get("acceptance", [])
    risks = data.get("risks", [])
    hit = [r for r in risks if r.get("state") != "未命中"]
    resolved = [r for r in hit if r.get("state") == "已决议"]
    row = [
        data.get("date", ""),
        data.get("slug", ""),
        data.get("next_stage", ""),
        f"{sum(1 for a in acceptance if a.get('closed'))}/{len(acceptance)}",
        f"{len(resolved)}/{len(hit)}",
        f"../{run_dir.resolve().name}/",
    ]
    lines = read_text(path).splitlines()
    table = find_table(lines)
    if table is None:
        raise ArtifactError(f"{path} 里找不到表格，格式已损坏")
    target_index = None
    for row_index in table.row_indices:
        cells = split_row(lines[row_index])
        if len(cells) >= 2 and cells[0] == row[0] and cells[1] == row[1]:
            target_index = row_index
            break
    if target_index is None:
        insert_at = (table.row_indices[-1] + 1) if table.row_indices else table.separator_index + 1
        lines.insert(insert_at, build_row(row))
    else:
        lines[target_index] = build_row(row)
    atomic_write(path, "\n".join(lines) + "\n")
    print(f"history-sync {row[1]}: 验收闭环 {row[3]}，风险决议 {row[4]}")
    return 0


# ------------------------------------------------------------------------ cli


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="req-align-v2 跨 run 沉淀（台账 / 踩坑库 / 时间线）")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="新增一条生效边界（需人工闸门确认）")
    p_add.add_argument("--run", required=True)
    p_add.add_argument("--module", required=True)
    p_add.add_argument("--statement", required=True)
    p_add.add_argument("--from-risk", dest="from_risk")
    p_add.add_argument("--confirmed-by", required=True, choices=("human", "agent"),
                       dest="confirmed_by")
    p_add.add_argument("--gate-outcome", required=True,
                       choices=("adopted", "revised", "rejected"), dest="gate_outcome")
    p_add.add_argument("--history-dir", dest="history_dir")
    p_add.set_defaults(func=cmd_add)

    p_sup = sub.add_parser("supersede", help="覆盖一条既有边界（双向标记）")
    p_sup.add_argument("bnd_id")
    p_sup.add_argument("--by", required=True)
    p_sup.add_argument("--new-statement", required=True, dest="new_statement")
    p_sup.add_argument("--reason", required=True)
    p_sup.add_argument("--confirmed-by", required=True, choices=("human", "agent"),
                       dest="confirmed_by")
    p_sup.add_argument("--gate-outcome", required=True,
                       choices=("adopted", "revised", "rejected"), dest="gate_outcome")
    p_sup.add_argument("--history-dir", dest="history_dir")
    p_sup.set_defaults(func=cmd_supersede)

    p_scan = sub.add_parser("scan", help="按关键词检索边界，只返回命中行 + 其踩坑")
    p_scan.add_argument("--keywords", required=True)
    p_scan.add_argument("--history-dir", dest="history_dir")
    p_scan.set_defaults(func=cmd_scan)

    p_pit = sub.add_parser("pitfall-add", help="给某条边界追加踩坑（同类 count+1）")
    p_pit.add_argument("--boundary", required=True)
    p_pit.add_argument("--phenomenon", required=True)
    p_pit.add_argument("--root-cause", required=True, dest="root_cause")
    p_pit.add_argument("--guard", required=True)
    p_pit.add_argument("--history-dir", dest="history_dir")
    p_pit.set_defaults(func=cmd_pitfall_add)

    p_hist = sub.add_parser("history-sync", help="重算该 run 在时间线里的闭环数字")
    p_hist.add_argument("run_dir")
    p_hist.add_argument("--history-dir", dest="history_dir")
    p_hist.set_defaults(func=cmd_history_sync)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ArtifactError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
