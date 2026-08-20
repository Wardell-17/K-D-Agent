# -*- coding: utf-8 -*-
"""K-D Agent 看板 · 纯读盘层（实验 021）
职责：只读 runs/ 目录下的落盘事实（任务卡 / cost.jsonl / events.jsonl / workspace 产物）。
零三方依赖（frontmatter 用内置迷你解析器），不 import streamlit / orchestrator，
不写任何文件——看板与引擎的唯一契约就是磁盘。Blueprint 托管 Python 沙箱也可直接 import。
"""
import json
import re
from pathlib import Path

AE_DIR = Path(__file__).resolve().parent.parent / "architect-engineer"


def _load_logging_dir() -> str:
    """从 config.yaml 抠 logging.dir（迷你解析，不引 yaml 包）。"""
    cfg = AE_DIR / "config.yaml"
    if cfg.is_file():
        m = re.search(r"(?m)^\s*dir:\s*[\"']?([\w./-]+)", cfg.read_text(encoding="utf-8"))
        if m:
            return m.group(1)
    return "runs"


RUNS_DIR = AE_DIR / _load_logging_dir()


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析 Markdown + 简化 YAML frontmatter（仅支持本项目卡片用到的平铺键值）。"""
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not m:
        return {}, text
    fm: dict = {}
    for line in m.group(1).splitlines():
        kv = re.match(r"^(\w+):\s*(.*)$", line.strip())
        if not kv:
            continue
        key, val = kv.group(1), kv.group(2).strip()
        if val.startswith("["):  # 简易数组: ["a", "b"]
            fm[key] = re.findall(r'"([^"]*)"', val)
        elif val.startswith('"'):
            fm[key] = val.strip('"')
        elif val.isdigit():
            fm[key] = int(val)
        else:
            fm[key] = val
    return fm, m.group(2)


def _section(body: str, name: str) -> str:
    m = re.search(rf"##\s*{re.escape(name)}\s*\n(.*?)(?=\n##\s|\Z)", body, re.DOTALL)
    return m.group(1).strip() if m else ""


def list_runs() -> list[Path]:
    """全部 run 目录，新的在前。"""
    if not RUNS_DIR.is_dir():
        return []
    return sorted((d for d in RUNS_DIR.iterdir() if d.is_dir()),
                  key=lambda d: d.name, reverse=True)


def load_cards(run_dir: Path) -> list[dict]:
    """读 run 目录 tasks/ 下全部任务卡，返回 dict 列表。"""
    cards = []
    tasks_dir = Path(run_dir) / "tasks"
    for f in sorted(tasks_dir.glob("*.md")):
        try:
            fm, body = _parse_frontmatter(f.read_text(encoding="utf-8"))
            goal = _section(body, "目标")
            notes = [l.lstrip("- ").strip() for l in
                     _section(body, "返工与备注").splitlines() if l.strip().startswith("-")]
            cards.append({
                "id": str(fm.get("id", f.stem.replace("card-", ""))),
                "title": str(fm.get("title", goal[:40])),
                "status": str(fm.get("status", "todo")),
                "owner": str(fm.get("owner", "")),
                "goal": goal,
                "depends_on": [str(x) for x in (fm.get("depends_on") or [])],
                "budget": int(fm.get("budget") or 0) or 12,
                "search_backend": str(fm.get("search_backend", "")),
                "notes": notes,
                "report": _section(body, "结构化回报"),
            })
        except Exception as e:
            cards.append({"id": f.stem, "title": f"（解析失败: {e}）", "status": "escalated",
                          "owner": "human", "goal": "", "depends_on": [], "budget": 0,
                          "report": "", "notes": [], "search_backend": ""})
    return cards


def load_cost(run_dir: Path) -> dict:
    """聚合 cost.jsonl：总额 + 按角色拆分。"""
    total = 0.0
    by_role: dict[str, dict] = {}
    path = Path(run_dir) / "cost.jsonl"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            role = r.get("role", "?")
            agg = by_role.setdefault(role, {"calls": 0, "tokens": 0, "cost": 0.0,
                                            "model": r.get("model", "?")})
            agg["calls"] += 1
            agg["tokens"] += r.get("prompt_tokens", 0) + r.get("completion_tokens", 0)
            agg["cost"] += r.get("cost_cny", 0.0)
            total += r.get("cost_cny", 0.0)
    return {"total": round(total, 6), "by_role": by_role}


def load_events(run_dir: Path) -> list[dict]:
    """读 events.jsonl 事件流（没有则空列表——老 run 兼容）。"""
    path = Path(run_dir) / "events.jsonl"
    events = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def workspace_files(run_dir: Path) -> list[Path]:
    """产物区文件列表。"""
    ws = Path(run_dir) / "workspace"
    if not ws.is_dir():
        return []
    return sorted(p for p in ws.rglob("*") if p.is_file())


def read_artifact(run_dir: Path, rel: str, limit: int = 40000) -> str:
    """读产物文件内容（截断保护）。"""
    p = (Path(run_dir) / "workspace" / rel).resolve()
    if not str(p).startswith(str((Path(run_dir) / "workspace").resolve())):
        return "（路径越界，已拒绝）"
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"（读取失败: {e}）"
    return text[:limit] + ("\n\n……（截断）" if len(text) > limit else "")
