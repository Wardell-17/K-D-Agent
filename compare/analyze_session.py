# -*- coding: utf-8 -*-
"""analyze_session.py — DeepSeek Harness 会话日志用量分析

用法：
    python analyze_session.py [会话目录|sessions根目录|某个 session.jsonl.zstd]

不给参数时默认分析 DSH_HOME（或 D:\\agent-project\\dsh-home）下最近一次运行的
所有会话（主会话 + 子代理会话），输出每个角色的模型、调用次数、工具调用数、耗时。

需要 Python 3.14+（使用标准库 compression.zstd 解码）。
"""
import json
import sys
from pathlib import Path
from compression import zstd

DSH_HOME = Path(r"D:\agent-project\dsh-home")


def decode_frames(path: Path) -> list[dict]:
    """session.jsonl.zstd 是多个 zstd 帧追加而成，按魔数切帧逐段解码。"""
    buf = path.read_bytes()
    magic = b"\x28\xb5\x2f\xfd"
    pos = []
    i = 0
    while True:
        j = buf.find(magic, i)
        if j < 0:
            break
        pos.append(j)
        i = j + 4
    events = []
    for k, start in enumerate(pos):
        end = pos[k + 1] if k + 1 < len(pos) else len(buf)
        try:
            text = zstd.decompress(buf[start:end]).decode("utf-8", "replace")
        except Exception:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return events


def summarize(session_dir: Path) -> dict | None:
    f = session_dir / "session.jsonl.zstd"
    if not f.exists():
        return None
    events = decode_frames(f)
    if not events:
        return None

    header = next((e for e in events if e.get("type") == "session"), {})
    models = {}          # (provider, model) -> llm 调用次数
    route = None         # request/context 里的本会话模型路由
    tool_calls = 0
    usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    first_t = last_t = None
    for e in events:
        t = e.get("time")
        if t:
            first_t = t if first_t is None else min(first_t, t)
            last_t = t if last_t is None else max(last_t, t)
        data = e.get("data") or {}
        # 路由信息：request/context 事件
        if e.get("type") == "request/context" and data.get("provider"):
            route = f"{data['provider']}/{data.get('model', '?')}"
        chunk = (data.get("chunk") or {})
        if not isinstance(chunk, dict):
            chunk = {}
        # token 用量：usage chunk（一个会话只跑一个模型，按会话累加即可）
        if chunk.get("type") == "usage":
            u = chunk.get("usage") or {}
            usage["input"] += u.get("inputTokens", 0)
            usage["output"] += u.get("outputTokens", 0)
            usage["cache_read"] += u.get("cacheReadTokens", 0)
            usage["cache_write"] += u.get("cacheWriteTokens", 0)
        # LLM 调用：finish chunk；replayState 带 provider 就用它，否则回退到路由
        if chunk.get("type") == "finish":
            rs = chunk.get("replayState") or {}
            key = (f"{rs['provider']}/{rs.get('model', '?')}" if rs.get("provider")
                   else route or "unknown")
            models[key] = models.get(key, 0) + 1
        # 工具调用计数
        msg = data.get("message") or {}
        for c in msg.get("content") or []:
            if isinstance(c, dict) and c.get("type") == "tool-call":
                tool_calls += 1

    model_name = next(iter(models), route or "unknown")
    return {
        "dir": session_dir.name.replace("session-", "")[:8],
        "cwd": header.get("cwd", "?"),
        "depth": header.get("delegationDepth", 0),
        "created": header.get("createdAt", 0),
        "models": models,
        "model": model_name,
        "usage": usage,
        "cost": estimate_cost(model_name, usage),
        "llm_calls": sum(models.values()),
        "tool_calls": tool_calls,
        "duration_s": round((last_t - first_t) / 1000, 1) if first_t and last_t else 0,
    }


# 单价表（元 / 百万 tokens），与 architect-engineer/config.yaml 保持一致
PRICES = {
    "deepseek": {"hit": 0.2, "miss": 1.0, "output": 2.0, "note": ""},
    "kimi":     {"hit": 4.0, "miss": 4.0, "output": 16.0, "note": "(订阅估算值)"},
}


def estimate_cost(model: str, usage: dict) -> tuple[float, str] | None:
    """按模型前缀匹配单价；cache_read 按命中价、其余输入按未命中价。"""
    for key, p in PRICES.items():
        if key in model:
            miss = max(usage["input"] - usage["cache_read"], 0) + usage["cache_write"]
            cost = (usage["cache_read"] * p["hit"] + miss * p["miss"]
                    + usage["output"] * p["output"]) / 1_000_000
            return cost, p["note"]
    return None


def find_latest_run_sessions(root: Path) -> list[Path]:
    """取 sessions 根目录下 mtime 最新的一组会话（同一工作目录、10 分钟窗口内）。"""
    all_dirs = sorted(root.glob("*/*/"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not all_dirs:
        return []
    newest = all_dirs[0]
    cutoff = newest.stat().st_mtime - 600
    return [d for d in all_dirs
            if d.parent == newest.parent and d.stat().st_mtime >= cutoff]


def session_dirs_under(p: Path) -> list[Path]:
    """兼容三种传参：session 目录本身 / 工作目录层 / sessions 根目录。"""
    if (p / "session.jsonl.zstd").exists():
        return [p]
    direct = [d for d in p.iterdir() if d.is_dir() and (d / "session.jsonl.zstd").exists()]
    if direct:
        return sorted(direct, key=lambda d: d.stat().st_mtime)
    return find_latest_run_sessions(p)


def main():
    arg = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if arg and arg.is_file():
        dirs = [arg.parent]
    elif arg:
        dirs = session_dirs_under(arg)
    else:
        dirs = find_latest_run_sessions(DSH_HOME / "sessions")

    if not dirs:
        print("没有找到会话记录。")
        return

    rows = []
    for d in sorted(dirs, key=lambda p: p.stat().st_mtime):
        s = summarize(d)
        if s:
            rows.append(s)

    total_calls = sum(r["llm_calls"] for r in rows)
    total_cost = sum(r["cost"][0] for r in rows if r["cost"])
    print(f"\n会话数: {len(rows)} ｜ LLM 调用总数: {total_calls} ｜ 估算总成本: ¥{total_cost:.4f}\n")
    for r in rows:
        role = "工程师(子代理)" if r["depth"] > 0 else "架构师(主会话)"
        print(f"[{role}] 会话 {r['dir']} ｜ 目录 {r['cwd']}")
        for m, n in sorted(r["models"].items()):
            print(f"    模型 {m} ｜ LLM 调用 {n} 次")
        u = r["usage"]
        if u["input"] or u["output"]:
            line = (f"    tokens: 输入 {u['input']:,}（缓存命中 {u['cache_read']:,}）"
                    f" ｜ 输出 {u['output']:,}")
            if r["cost"]:
                line += f" ｜ 估算成本 ¥{r['cost'][0]:.4f}{r['cost'][1]}"
            print(line)
        print(f"    工具调用 {r['tool_calls']} 次 ｜ 耗时 {r['duration_s']} 秒")
    print()


if __name__ == "__main__":
    main()
