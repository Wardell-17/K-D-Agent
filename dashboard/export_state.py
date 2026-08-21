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


def _is_discarded(r: Path) -> bool:
    rp = r / "report.json"
    if not rp.exists():
        return False
    try:
        return bool(json.loads(rp.read_text(encoding="utf-8")).get("discarded"))
    except Exception:
        return False


def export(run_name: str | None = None) -> dict:
    runs = reader.list_runs()
    if not runs:
        return {"error": "没有任何 run"}
    # 累计总账：全部 run 的 cost.jsonl 加总（含废弃 run——钱已经花了，账要认）
    # 同时给出"有效口径"：未废弃 run 的单数与平均每单成本（汇报/简历可用）
    lifetime = {"cost_cny": 0.0, "llm_calls": 0, "runs": len(runs),
                "valid_runs": 0, "valid_cost": 0.0, "discarded_runs": 0}
    for r in runs:
        c = reader.load_cost(r)
        lifetime["cost_cny"] += c["total"]
        lifetime["llm_calls"] += sum(v["calls"] for v in c["by_role"].values())
        if _is_discarded(r):
            lifetime["discarded_runs"] += 1
        else:
            lifetime["valid_runs"] += 1
            lifetime["valid_cost"] += c["total"]
    lifetime["cost_cny"] = round(lifetime["cost_cny"], 4)
    lifetime["valid_cost"] = round(lifetime["valid_cost"], 4)
    lifetime["avg_cost"] = round(lifetime["valid_cost"] / lifetime["valid_runs"], 4) \
        if lifetime["valid_runs"] else 0.0
    # run 切换器列表（最近 15 个，标注废弃）
    runs_list = [{"name": r.name, "discarded": _is_discarded(r)} for r in runs[:15]]
    run_dir = next((r for r in runs if r.name == run_name), runs[0]) if run_name else runs[0]
    # 主视图 run 选择：优先"有实质内容"的 run（有报告/有成本/有事件），
    # 只拆了卡未执行的 plan-only run 不占主视图，进待审批收件箱
    if not run_name:
        for r in runs:
            rp = r / "report.json"
            if rp.exists():
                try:
                    if json.loads(rp.read_text(encoding="utf-8")).get("discarded"):
                        continue          # 废弃 run 不进主视图
                except Exception:
                    pass
                run_dir = r
                break
            cs = reader.load_cards(r)
            if any(c["status"] != "todo" for c in cs):   # 执行中的 run（尚未出报告）
                run_dir = r
                break
    # 待审批收件箱：最近 10 个 run 中，无 report.json（未执行/未废弃）且卡全为 todo 的
    pending_approvals = []
    for r in runs[:10]:
        if r == run_dir or (r / "report.json").exists():
            continue
        cs = reader.load_cards(r)
        if cs and all(c["status"] == "todo" for c in cs):
            pending_approvals.append({
                "run": r.name,
                "cards": [{"id": c["id"], "title": c["title"], "budget": c["budget"]}
                          for c in cs],
            })
    cards = reader.load_cards(run_dir)
    cost = reader.load_cost(run_dir)
    events_all = reader.load_events(run_dir)
    # 事件窗口策略：验收/评审事件是证据本体，单独保量（各留 25 条），
    # 其余高频事件（tool 等）留最近 35 条——防止 verify 被刷出窗口导致验收记录空白
    key_events = [e for e in events_all if e.get("type") in ("verify", "review")][-25:]
    other_events = [e for e in events_all if e.get("type") not in ("verify", "review")][-35:]
    events = sorted(key_events + other_events, key=lambda e: e.get("ts", ""))
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
        "events": events,
        "pending_approvals": pending_approvals,
        "lifetime": lifetime,
        "runs_list": runs_list,
        "artifacts": _collect_artifacts(run_dir, ws, files, events_all),
    }


def _inline_text(p: Path, limit: int = 6000):
    """小文本文件内联进快照，供看板点击预览（沙箱 iframe 读不到本地文件）"""
    try:
        if p.stat().st_size > 512 * 1024:
            return None
        raw = p.read_bytes()
        if b"\x00" in raw[:4096]:
            return None  # 二进制不内联
        return raw.decode("utf-8", errors="replace")[:limit]
    except Exception:
        return None


def _collect_artifacts(run_dir: Path, ws: Path, files, events_all):
    arts = []
    # 1) workspace 内文件：过滤 <64B 的噪音（工程师手滑重定向产物）
    for f in files[:30]:
        size = f.stat().st_size
        if size < 64:
            continue
        arts.append({"path": str(f.relative_to(ws)), "size": size,
                     "external": False, "content": _inline_text(f)})
    # 2) 外部产物：从事件流 write_file 的绝对路径里捞终稿（写在 workspace 外的交付物）
    seen = {str(a["path"]).lower() for a in arts}
    import re
    for e in events_all:
        if e.get("type") != "tool" or e.get("tool") != "write_file":
            continue
        raw = e.get("args") or ""
        try:
            p_str = json.loads(raw).get("path", "")
        except Exception:
            # 日志 args 被截断导致 JSON 不完整 → 正则抢救 path 字段（含 JSON 转义）
            m = re.search(r'"path"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
            if not m:
                continue
            try:
                p_str = json.loads('"' + m.group(1) + '"')
            except Exception:
                continue
        if not p_str:
            continue
        p = Path(p_str)
        if not p.is_absolute() or not p.is_file():
            continue
        try:
            p.relative_to(ws)  # workspace 内的上面已收
            continue
        except ValueError:
            pass
        key = str(p).lower()
        if key in seen:
            continue
        seen.add(key)
        arts.append({"path": str(p), "size": p.stat().st_size,
                     "external": True, "content": _inline_text(p)})
    return arts


if __name__ == "__main__":
    snap = export(sys.argv[1] if len(sys.argv) > 1 else None)
    out = Path(__file__).resolve().parent / "state.json"
    out.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: (v if not isinstance(v, list) else f"<{len(v)} 项>") for k, v in snap.items()},
                     ensure_ascii=False))
    print(f"[ok] {out}")
