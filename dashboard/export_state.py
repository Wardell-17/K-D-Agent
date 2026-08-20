# -*- coding: utf-8 -*-
"""把最新（或指定）run 的状态快照导出为 state.json —— Widget 大屏的数据契约。
用法: python export_state.py [run目录名]   输出: dashboard/state.json + stdout
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reader  # noqa: E402


def load_role_stats(run_dir: Path) -> list[dict]:
    """按角色聚合 cost.jsonl，含人设数据源：缓存命中率、峰值单轮上下文。"""
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
            agg = by_role.setdefault(role, {
                "role": role, "model": r.get("model", "?"), "calls": 0, "tokens": 0,
                "cost": 0.0, "cache_hit": 0, "prompt": 0, "peak_prompt": 0})
            agg["calls"] += 1
            agg["tokens"] += r.get("prompt_tokens", 0) + r.get("completion_tokens", 0)
            agg["cost"] += r.get("cost_cny", 0.0)
            agg["cache_hit"] += r.get("cache_hit", 0)
            agg["prompt"] += r.get("prompt_tokens", 0)
            agg["peak_prompt"] = max(agg["peak_prompt"], r.get("prompt_tokens", 0))
    for agg in by_role.values():
        agg["cache_rate"] = round(agg["cache_hit"] / agg["prompt"], 3) if agg["prompt"] else 0.0
        agg["cost"] = round(agg["cost"], 6)
    return list(by_role.values())


def export(run_name: str | None = None) -> dict:
    runs = reader.list_runs()
    if not runs:
        return {"error": "没有任何 run"}
    run_dir = next((r for r in runs if r.name == run_name), runs[0]) if run_name else runs[0]
    cards = reader.load_cards(run_dir)
    cost = reader.load_cost(run_dir)
    events = reader.load_events(run_dir)
    files = reader.workspace_files(run_dir)
    ws = run_dir / "workspace"
    report_path = run_dir / "report.json"
    task = ""
    if report_path.is_file():
        try:
            task = json.loads(report_path.read_text(encoding="utf-8")).get("task", "")
        except Exception:
            pass
    return {
        "run": run_dir.name,
        "task": task,
        "totals": {
            "cards": len(cards),
            "done": sum(1 for c in cards if c["status"] == "done"),
            "escalated": sum(1 for c in cards if c["status"] == "escalated"),
            "cost_cny": cost["total"],
            "llm_calls": sum(v["calls"] for v in cost["by_role"].values()),
        },
        "roles": load_role_stats(run_dir),
        "cards": [{
            "id": c["id"], "title": c["title"], "status": c["status"],
            "owner": c["owner"], "budget": c["budget"], "depends_on": c["depends_on"],
            "notes": c["notes"][-3:],
        } for c in cards],
        "events": events[-40:],
        "artifacts": [{"path": str(f.relative_to(ws)), "size": f.stat().st_size}
                      for f in files[:30]],
    }


if __name__ == "__main__":
    snap = export(sys.argv[1] if len(sys.argv) > 1 else None)
    out = Path(__file__).resolve().parent / "state.json"
    out.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: (v if not isinstance(v, list) else f"<{len(v)} 项>") for k, v in snap.items()},
                     ensure_ascii=False))
    print(f"[ok] {out}")
