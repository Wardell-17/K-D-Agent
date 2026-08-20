# -*- coding: utf-8 -*-
"""K-D Agent 看板 · 纯读盘层（实验 021）
职责：只读 runs/ 目录下的落盘事实（任务卡 / cost.jsonl / events.jsonl / workspace 产物），
不 import streamlit，不写任何文件——看板与引擎的唯一契约就是磁盘。
"""
import json
import sys
from pathlib import Path

AE_DIR = Path(__file__).resolve().parent.parent / "architect-engineer"
sys.path.insert(0, str(AE_DIR))
from orchestrator import CONFIG, load_card  # noqa: E402  复用卡片解析，避免两套 frontmatter 逻辑

RUNS_DIR = AE_DIR / CONFIG["logging"]["dir"]


def list_runs() -> list[Path]:
    """全部 run 目录，新的在前。"""
    if not RUNS_DIR.is_dir():
        return []
    return sorted((d for d in RUNS_DIR.iterdir() if d.is_dir()),
                  key=lambda d: d.name, reverse=True)


def load_cards(run_dir: Path) -> list[dict]:
    """读 run 目录 tasks/ 下全部任务卡，返回 dict 列表（按 id 排序）。"""
    cards = []
    tasks_dir = Path(run_dir) / "tasks"
    for f in sorted(tasks_dir.glob("*.md")):
        try:
            packet, card = load_card(f)
        except Exception as e:
            cards.append({"id": f.stem, "title": f"（解析失败: {e}）", "status": "escalated",
                          "owner": "human", "goal": "", "depends_on": [], "budget": 0,
                          "report": "", "notes": []})
            continue
        cards.append({
            "id": card.task_id, "title": card.title, "status": card.status,
            "owner": card.owner, "goal": card.goal, "depends_on": card.depends_on,
            "budget": card.budget or packet.remaining_budget,
            "report": card.report, "notes": card.notes,
            "search_backend": card.search_backend,
        })
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
    """产物区文件列表（相对路径）。"""
    ws = Path(run_dir) / "workspace"
    if not ws.is_dir():
        return []
    return sorted(p for p in ws.rglob("*") if p.is_file())


def read_artifact(run_dir: Path, rel: str, limit: int = 40000) -> str:
    """读产物文件内容（截断保护，防超大文件撑爆页面）。"""
    p = (Path(run_dir) / "workspace" / rel).resolve()
    if not str(p).startswith(str((Path(run_dir) / "workspace").resolve())):
        return "（路径越界，已拒绝）"
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"（读取失败: {e}）"
    return text[:limit] + ("\n\n……（截断）" if len(text) > limit else "")
