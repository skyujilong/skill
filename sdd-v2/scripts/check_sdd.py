#!/usr/bin/env python3
"""sdd-v2 结构与 AC 覆盖检查（只读）。

用法: check_sdd.py <sdd_dir> --run-dir <req-align run 目录>
退出码: 0 全部通过 / 1 有 FAIL / 2 用法或上游契约错误。

只证明结构与 AC 覆盖：目录命名、必备文件、矩阵行与上游 AC 一一对应、每行有 G/W/T、
P0 行带失败/边界例。**不证明规格内容正确**——那需要独立审阅。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REQUIRED_FILES = ("README.md", "01-overview.md", "acceptance-matrix.md")
AC_RE = re.compile(r"AC-\d+")
AC_CITE_RE = re.compile(r"(?<![\w-])AC-\d+(?!\d)")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
HEADING_RE = re.compile(r"^##\s+(.*?)\s*$")
LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
SEP_RE = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$")
GWT_WORD_RE = re.compile(r"(?<![A-Za-z0-9_])(given|when|then)(?![A-Za-z0-9_])")
GWT_ORDER = ("given", "when", "then")
GWT_ORDINARY = ("应当", "每当", "适当", "相当", "否则", "规则", "原则", "准则", "法则")
RUN_DIRNAME_RE = re.compile(r"^req-align-(\d{4}-\d{2}-\d{2})-(.+)$")
SOURCE_FILES = ("align.md", "arch-risk.md", "acceptance.md")  # 与 req-align-v2 source_sha256 约定一致，镜像计算
PRIORITIES = ("P0", "P1", "P2")
PLACEHOLDER_WHOLE = {"", "-", "—", "–", "略", "无", "n/a", "na", "tbd", "todo", "待定", "待补", "待补充", "…", "..."}
PLACEHOLDER_SUB = re.compile(r"\bTBD\b|\bTODO\b|待定|待补", re.I)
FAILURE_RE = re.compile(
    "失败|错误|异常|边界|越权|拒绝|超时|为空|空值|空输入|空字符串|空列表|非法|无权|禁止|"
    r"(?<![A-Za-z0-9_])(?:error|fail|failure|invalid|reject|rejected|timeout|boundary|"
    r"forbidden|unauthorized|denied)(?![A-Za-z0-9_])", re.I)
OVERVIEW_SECTIONS = ("目标", "范围", "功能需求", "非功能需求", "错误与边界")
OWNER_RE = re.compile(r"负责人|owner|@", re.I)

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"


class UsageError(Exception):
    pass


class Report:
    def __init__(self):
        self.fails = 0

    def line(self, level: str, msg: str):
        if level == FAIL:
            self.fails += 1
        print(f"[{level}] {msg}")


def has_gwt(spec: str) -> bool:
    """Given/When/Then（或 给定/当/则）按序出现；先剔除 应当/否则 等普通词再归一化。"""
    for w in GWT_ORDINARY:
        spec = spec.replace(w, " ")
    spec = spec.replace("给定", " given ").replace("当", " when ").replace("则", " then ")
    want = iter(GWT_ORDER)
    need = next(want)
    for m in GWT_WORD_RE.finditer(spec.lower()):
        if m.group(1) == need:
            need = next(want, None)
            if need is None:
                return True
    return False


def run_slug(run_dir: Path) -> str:
    """与 align_state.parse_run_dirname 同口径：slug 取自 run 目录名。"""
    m = RUN_DIRNAME_RE.match(run_dir.resolve().name)
    if not m:
        raise UsageError(f"run 目录名不合规范: {run_dir.resolve().name}（应为 req-align-<yyyy-mm-dd>-<slug>）")
    return m.group(2)


def check_freshness(rep: "Report", run_dir: Path, recorded) -> None:
    """handoff.json 必须是三份源 Markdown 当前字节的派生，否则契约已陈旧。"""
    hint = f"先运行 `python3 <req-align-v2>/scripts/align_state.py sync {run_dir}`"
    if not isinstance(recorded, dict) or set(recorded) != set(SOURCE_FILES):
        rep.line(FAIL, f"handoff.json 缺少合法的 source_sha256（键须恰为 {', '.join(SOURCE_FILES)}）: {hint}")
        return
    before = rep.fails
    for name in SOURCE_FILES:
        stored, path = recorded[name], run_dir / name
        if not isinstance(stored, str) or not re.fullmatch(r"[0-9a-f]{64}", stored):
            rep.line(FAIL, f"source_sha256[{name}] 不是 64 位小写十六进制: {hint}")
        elif not path.is_file():
            rep.line(FAIL, f"上游源文件缺失: {path}: {hint}")
        else:
            try:
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as exc:
                rep.line(FAIL, f"无法读取 {path}: {exc}")
                continue
            if actual != stored:
                rep.line(FAIL, f"{name} 在 handoff.json 生成后被改动（source_sha256 不一致）: {hint}")
    if rep.fails == before:
        rep.line(PASS, "handoff.json 与三份源文件一致（新鲜）")


def read_lines(path: Path) -> list:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n").split("\n")


def outside_fences(lines: list) -> list:
    """返回 (行号, 文本) 序列，剔除围栏代码块（含围栏行）。"""
    out, fenced = [], False
    for i, text in enumerate(lines):
        if FENCE_RE.match(text):
            fenced = not fenced
            continue
        if not fenced:
            out.append((i, text))
    return out


def load_upstream(run_dir: Path):
    path = run_dir / "handoff.json"
    if not path.is_file():
        raise UsageError(f"缺少 {path}: 先对上游 run 跑 `align_state.py sync`")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UsageError(f"{path} 无法解析: {exc}")
    if not isinstance(data, dict):
        raise UsageError(f"{path} 顶层必须是对象")
    slug = data.get("slug")
    acs = data.get("acceptance")
    if not isinstance(slug, str) or not slug:
        raise UsageError(f"{path} 缺少字符串字段 slug")
    if not isinstance(acs, list) or not all(
            isinstance(a, dict) and isinstance(a.get("id"), str) and isinstance(a.get("priority"), str)
            for a in acs):
        raise UsageError(f"{path} 的 acceptance 必须是含 id/priority 的对象列表")
    for a in acs:
        if a["priority"] not in PRIORITIES:
            raise UsageError(f"{path} 中 {a['id']} 的 priority `{a['priority']}` 非法，须为 {'/'.join(PRIORITIES)}")
    return slug, data.get("source_sha256"), {a["id"]: a["priority"] for a in acs}


def split_cells(line: str) -> list:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", s)]


def parse_matrix(lines: list):
    """返回 (是否找到合规表头, 行列表[(AC, 规格, 模块, 备注)])；聚合围栏外所有合规表格，跳过分隔行。"""
    seq = outside_fences(lines)
    found, rows, k = False, [], 0
    while k < len(seq):
        text = seq[k][1]
        cells = split_cells(text) if text.lstrip().startswith("|") else []
        if (len(cells) >= 4 and cells[0] == "AC" and cells[1].startswith("规格")
                and cells[2] == "覆盖模块" and cells[3] == "备注"
                and k + 1 < len(seq) and SEP_RE.match(seq[k + 1][1].strip())):
            found = True
            k += 2
            while k < len(seq) and seq[k][1].lstrip().startswith("|"):
                t = seq[k][1]
                k += 1
                if SEP_RE.match(t.strip()):
                    continue
                c = split_cells(t) + [""] * 4
                rows.append(tuple(c[:4]))
            continue
        k += 1
    return found, rows


def is_placeholder(cell: str) -> bool:
    return cell.strip().lower() in PLACEHOLDER_WHOLE or bool(PLACEHOLDER_SUB.search(cell))


def check_naming(rep: Report, sdd: Path, run_dir: Path, slug: str, handoff_slug: str):
    if handoff_slug != slug:
        rep.line(FAIL, f"handoff.json slug differs from run dir name (handoff `{handoff_slug}` vs dir `{slug}`); "
                       f"sync: 先运行 `python3 <req-align-v2>/scripts/align_state.py sync {run_dir}`")
    pattern = rf"sdd-\d{{4}}-\d{{2}}-\d{{2}}-{re.escape(slug)}"
    if re.fullmatch(pattern, sdd.resolve().name):
        rep.line(PASS, f"目录名 {sdd.resolve().name} 符合 sdd-<日期>-{slug}")
    else:
        rep.line(FAIL, f"目录名 {sdd.resolve().name} 不合规范: 应为 sdd-<yyyy-mm-dd>-{slug}（精确 slug，不允许额外后缀）")
    if sdd.resolve().parent == run_dir.resolve().parent:
        rep.line(PASS, "与上游 run 目录同级")
    else:
        rep.line(FAIL, f"必须与上游 run 目录同级（共用 docs/）: 应位于 {run_dir.resolve().parent}")


def check_files(rep: Report, sdd: Path) -> bool:
    ok = True
    for name in REQUIRED_FILES:
        p = sdd / name
        if p.is_file() and p.read_text(encoding="utf-8").strip():
            rep.line(PASS, f"{name} 存在且非空")
        else:
            ok = False
            rep.line(FAIL, f"{name} 缺失或为空")
    return ok


def check_matrix(rep: Report, path: Path, upstream: dict):
    valid, rows = parse_matrix(read_lines(path))
    if not valid:
        rep.line(FAIL, "acceptance-matrix.md 没有合规表格（表头须含 AC / 规格 / 覆盖模块 / 备注，且在围栏代码块之外）")
        return
    rep.line(PASS, f"矩阵表头合规，共 {len(rows)} 行")
    seen = {}
    for ac, spec, module, note in rows:
        key = ac.strip("*` ")
        if not AC_RE.fullmatch(key):
            rep.line(FAIL, f"行 AC 列 `{ac}` 不是 AC-<数字>")
            continue
        seen.setdefault(key, []).append((spec, module, note))
    missing = [i for i in upstream if i not in seen]
    dup = [i for i, v in seen.items() if len(v) > 1]
    extra = [i for i in seen if i not in upstream]
    if missing:
        rep.line(FAIL, f"矩阵缺少上游 AC: {', '.join(missing)}")
    if dup:
        rep.line(FAIL, f"AC 重复出现（每个 AC 恰好一行，子用例用 <br> 写在同一行）: {', '.join(dup)}")
    if extra:
        rep.line(FAIL, f"矩阵含上游没有的 id: {', '.join(extra)}——SDD must not invent or renumber ids; "
                       "add it via req-align-v2 first")
    if not (missing or dup or extra):
        rep.line(PASS, "矩阵行与上游 AC 一一对应")
    bad = 0
    for ac_id, entries in seen.items():
        if ac_id not in upstream:
            continue
        spec, module, note = entries[0]
        problems = []
        if not has_gwt(spec):
            problems.append("规格缺少按序出现的 Given→When→Then（或 给定→当→则）")
        if is_placeholder(spec):
            problems.append("规格是占位内容")
        if is_placeholder(module):
            problems.append("覆盖模块为空或占位")
        if upstream[ac_id] == "P0" and not FAILURE_RE.search(spec + " " + note):
            problems.append("P0 行未提及失败/边界例（规格或备注）")
        if problems:
            bad += 1
            rep.line(FAIL, f"{ac_id}: " + "；".join(problems))
    if not bad:
        rep.line(PASS, "每行规格、覆盖模块与 P0 失败/边界例检查通过")


def sections(seq: list) -> list:
    """按二级标题切分 (标题, [正文行])；seq 已去围栏。"""
    out, cur = [], None
    for _, text in seq:
        m = HEADING_RE.match(text)
        if m:
            cur = (m.group(1), [])
            out.append(cur)
        elif cur is not None:
            cur[1].append(text)
    return out


def list_items(body: list) -> list:
    items = []
    for text in body:
        m = LIST_RE.match(text)
        if m:
            items.append(m.group(1))
        elif items and text.startswith((" ", "\t")) and text.strip():
            items[-1] += " " + text.strip()
    return items


def check_overview(rep: Report, path: Path, upstream: dict):
    lines = read_lines(path)
    seq = outside_fences(lines)
    secs = sections(seq)
    heads = [h for h, _ in secs]
    absent = [kw for kw in OVERVIEW_SECTIONS if not any(kw in h for h in heads)]
    if absent:
        rep.line(FAIL, f"01-overview.md 缺少二级标题: {', '.join(absent)}")
    else:
        rep.line(PASS, "01-overview.md 含全部必备二级标题")
    cited = set(AC_CITE_RE.findall("\n".join(t for _, t in seq)))
    uncited = [i for i in upstream if i not in cited]
    if uncited:
        rep.line(WARN, f"01-overview.md 未引用这些 AC: {', '.join(uncited)}")
    else:
        rep.line(PASS, "01-overview.md 引用了全部上游 AC")
    unowned = 0
    for head, body in secs:
        if "开放问题" in head or "假设" in head:
            for item in list_items(body):
                if not OWNER_RE.search(item):
                    unowned += 1
                    rep.line(WARN, f"开放问题/假设缺少负责人（负责人/owner/@）: {item[:40]}")
    if not unowned:
        rep.line(PASS, "开放问题/假设均有负责人（或无此类条目）")


def check_readme(rep: Report, path: Path, run_dir: Path):
    if run_dir.resolve().name in path.read_text(encoding="utf-8"):
        rep.line(PASS, "README.md 指向上游 run 目录")
    else:
        rep.line(WARN, f"README.md 未提及上游 run 目录名 {run_dir.resolve().name}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="检查 sdd-<date>-<slug>/ 的结构与 AC 覆盖（只读）")
    ap.add_argument("sdd_dir")
    ap.add_argument("--run-dir", required=True)
    args = ap.parse_args(argv)
    sdd, run_dir = Path(args.sdd_dir), Path(args.run_dir)
    try:
        if not run_dir.is_dir():
            raise UsageError(f"run 目录不存在: {run_dir}")
        if not sdd.is_dir():
            raise UsageError(f"SDD 目录不存在: {sdd}")
        slug = run_slug(run_dir)
        handoff_slug, recorded, upstream = load_upstream(run_dir)
    except UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    rep = Report()
    check_freshness(rep, run_dir, recorded)
    check_naming(rep, sdd, run_dir, slug, handoff_slug)
    steps = [(check_files, (rep, sdd))]
    if (sdd / "acceptance-matrix.md").is_file():
        steps.append((check_matrix, (rep, sdd / "acceptance-matrix.md", upstream)))
    if (sdd / "01-overview.md").is_file():
        steps.append((check_overview, (rep, sdd / "01-overview.md", upstream)))
    if (sdd / "README.md").is_file():
        steps.append((check_readme, (rep, sdd / "README.md", run_dir)))
    for fn, fargs in steps:
        try:
            fn(*fargs)
        except (UnicodeDecodeError, OSError) as exc:
            rep.line(FAIL, f"{fn.__name__} 无法读取产物（须为 UTF-8 文本）: {exc}")
    if rep.fails:
        print(f"result: FAIL ({rep.fails} 项失败)")
        return 1
    print("result: PASS")
    print(f"下一步: python3 <req-align-v2>/scripts/align_state.py stage-add {run_dir} --stage sdd --dir {sdd}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
