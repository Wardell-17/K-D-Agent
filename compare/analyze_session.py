# -*- coding: utf-8 -*-
"""analyze_session.py — DeepSeek Harness 会话账本分析工具（官方版）

用法：
    python D:\\agent-project\\compare\\analyze_session.py [会话目录|会话根|--probe]

- 不传参数：自动定位 DSH_HOME\\sessions 下最近的主会话，并分析其全部子代理会话
- 传会话目录：分析该目录及其子代理；传会话根（--D-xxx-- 层）：分析其下最近一组
- --probe：打印前几条事件样例，用于核对 JSONL schema

归属判定：首选会话头 parentSession 字段（可靠），时间窗启发式仅作兜底。
用量口径：assistant/message 事件 data.usage（含 reasoningTokens），
          老版本会话无此字段时回退 assistant/chunk 的 usage 块。
价格口径：architect-engineer/config.yaml 的人工核实价（元/百万 tokens），
          Kimi K3 为订阅额度，金额为数量级估算并明确标注。
需要 Python 3.14+（标准库 compression.zstd）；3.12 环境自动尝试 zstandard 包。
"""
import json
import sys
from pathlib import Path

DSH_HOME = Path(r"D:\agent-project\dsh-home")

try:
    from compression import zstd as _zstd            # Python 3.14+
except ImportError:
    try:
        import zstandard as _zstd_fallback           # pip 包兜底
        class _Z:
            @staticmethod
            def decompress(b):
                return _zstd_fallback.ZstdDecompressor().stream_reader(
                    __import__("io").BytesIO(b), read_across_frames=True).read()
        _zstd = _Z()
    except ImportError:
        sys.exit("需要 Python 3.14+（compression.zstd）或 pip install zstandard")


def decode_frames(path: Path) -> list[dict]:
    """session.jsonl.zstd 是多个 zstd 帧追加而成，按魔数切帧逐段解码。"""
    buf = path.read_bytes()
    magic = b"\x28\xb5\x2f\xfd"
    pos, i = [], 0
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
            text = _zstd.decompress(buf[start:end]).decode("utf-8", "replace")
        except Exception:
            continue
        for line in text.splitlines():
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return events


# 单价表（元 / 百万 tokens）——以 architect-engineer/config.yaml 人工核实价为准
PRICES = {
    "deepseek": {"hit": 0.2, "miss": 1.0, "output": 2.0, "note": ""},
    "kimi":     {"hit": 4.0, "miss": 4.0, "output": 16.0, "note": "（订阅估算值）"},
}


def estimate_cost(model: str, usage: dict):
    for key, p in PRICES.items():
        if key in model:
            miss = max(usage["input"] - usage["cache_read"], 0) + usage["cache_write"]
            cost = (usage["cache_read"] * p["hit"] + miss * p["miss"]
                    + usage["output"] * p["output"]) / 1_000_000
            return cost, p["note"]
    return None


def summarize(session_dir: Path) -> dict | None:
    f = session_dir / "session.jsonl.zstd"
    if not f.exists():
        return None
    events = decode_frames(f)
    if not events:
        return None

    header = next((e for e in events if e.get("type") == "session"), {})
    route = None
    model_seen = None
    llm_calls = 0
    tool_calls = 0
    extra_llm = 0          # 无 usage 的附加 LLM 请求（标题生成、web 搜索等）
    usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "reasoning": 0}
    saw_msg_usage = False
    first_t = last_t = None

    for e in events:
        t = e.get("time")
        if t:
            first_t = t if first_t is None else min(first_t, t)
            last_t = t if last_t is None else max(last_t, t)
        etype = e.get("type", "")
        data = e.get("data") or {}

        if etype == "request/context" and data.get("provider"):
            route = f"{data['provider']}/{data.get('model', '?')}"

        if etype == "assistant/message":
            llm_calls += 1
            msg = data.get("message") or {}
            src = msg.get("source") or {}
            if src.get("provider"):
                model_seen = f"{src['provider']}/{src.get('model', '?')}"
            for c in msg.get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool-call":
                    tool_calls += 1
            u = (data.get("usage") or msg.get("usage")) or {}
            if u:
                saw_msg_usage = True
                usage["input"] += u.get("inputTokens", 0)
                usage["output"] += u.get("outputTokens", 0)
                usage["cache_read"] += u.get("cacheReadTokens", 0)
                usage["cache_write"] += u.get("cacheWriteTokens", 0)
                usage["reasoning"] += u.get("reasoningTokens", 0)

        elif etype == "assistant/chunk":
            chunk = data.get("chunk") or {}
            if isinstance(chunk, dict) and chunk.get("type") == "usage" and not saw_msg_usage:
                u = chunk.get("usage") or {}
                usage["input"] += u.get("inputTokens", 0)
                usage["output"] += u.get("outputTokens", 0)
                usage["cache_read"] += u.get("cacheReadTokens", 0)
                usage["cache_write"] += u.get("cacheWriteTokens", 0)
            # 老版本会话没有 assistant/message 时，用 finish 块数 LLM 调用
            if isinstance(chunk, dict) and chunk.get("type") == "finish":
                rs = chunk.get("replayState") or {}
                if rs.get("provider"):
                    model_seen = f"{rs['provider']}/{rs.get('model', '?')}"

        elif etype in ("web/deepseek-search-llm-request", "session/title-llm-request"):
            extra_llm += 1

    # 老版本会话（无 assistant/message）兜底：finish 块数 = LLM 调用数
    if llm_calls == 0:
        llm_calls = sum(
            1 for e in events
            if e.get("type") == "assistant/chunk"
            and ((e.get("data") or {}).get("chunk") or {}).get("type") == "finish")

    model = model_seen or route or "unknown"
    return {
        "id": header.get("id", session_dir.name),
        "dir": session_dir.name.replace("session-", "")[:8],
        "cwd": header.get("cwd", "?"),
        "depth": header.get("delegationDepth", 0),
        "parent": header.get("parentSession"),
        "created": header.get("createdAt", 0),
        "model": model,
        "llm_calls": llm_calls,
        "tool_calls": tool_calls,
        "extra_llm": extra_llm,
        "usage": usage,
        "cost": estimate_cost(model, usage),
        "duration_s": round((last_t - first_t) / 1000, 1) if first_t and last_t else 0,
        "first_t": first_t or 0,
    }


def discover(root: Path) -> list[Path]:
    """sessions 根目录下，找最近的主会话 + 其子代理（parentSession 优先，时间窗兜底）。"""
    all_dirs = [d for d in root.glob("*/*/") if (d / "session.jsonl.zstd").exists()]
    if not all_dirs:
        return []
    infos = []
    for d in all_dirs:
        s = summarize(d)
        if s:
            infos.append((d, s))
    # 最近的主会话：无 parentSession 且最后事件最新
    mains = [(d, s) for d, s in infos if not s["parent"]]
    if not mains:
        return [max(infos, key=lambda x: x[1]["first_t"])[0]]
    main_d, main_s = max(mains, key=lambda x: x[1]["first_t"])
    picked = [main_d]
    for d, s in infos:
        if d is main_d:
            continue
        if s["parent"] and s["parent"] == main_s["id"]:
            picked.append(d)
    return picked


def session_dirs_under(p: Path) -> list[Path]:
    if (p / "session.jsonl.zstd").exists():
        return [p]
    direct = [d for d in p.iterdir()
              if d.is_dir() and (d / "session.jsonl.zstd").exists()]
    if direct:
        return sorted(direct, key=lambda d: d.stat().st_mtime)
    return discover(p)


def probe(path: Path):
    events = decode_frames(path)[:5]
    for e in events:
        print(json.dumps(e, ensure_ascii=False)[:400])
    print(f"… 共 {len(decode_frames(path))} 条事件")


def main():
    args = [a for a in sys.argv[1:] if a != "--probe"]
    if "--probe" in sys.argv[1:]:
        target = Path(args[0]) if args else None
        if target and target.is_dir():
            target = target / "session.jsonl.zstd"
        if not target or not target.exists():
            sys.exit("--probe 需要会话文件或目录路径")
        probe(target)
        return

    arg = Path(args[0]) if args else None
    if arg and arg.is_file():
        dirs = [arg.parent]
    elif arg:
        dirs = session_dirs_under(arg)
    else:
        dirs = discover(DSH_HOME / "sessions")

    if not dirs:
        print("没有找到会话记录。")
        return

    rows = [s for s in (summarize(d) for d in dirs) if s]
    rows.sort(key=lambda r: (r["depth"], r["created"]))

    total_cost = sum(r["cost"][0] for r in rows if r["cost"])
    total_calls = sum(r["llm_calls"] for r in rows)
    print(f"\n会话数: {len(rows)} ｜ LLM 调用总数: {total_calls} ｜ 估算总成本: ¥{total_cost:.4f}\n")
    for r in rows:
        role = "工程师(子代理)" if r["depth"] > 0 or r["parent"] else "架构师(主会话)"
        print(f"[{role}] 会话 {r['dir']} ｜ 模型 {r['model']}")
        u = r["usage"]
        line = (f"    LLM 调用 {r['llm_calls']} ｜ 工具调用 {r['tool_calls']}"
                f" ｜ 输入 {u['input']:,}（缓存命中 {u['cache_read']:,}）"
                f" ｜ 输出 {u['output']:,}")
        if u["reasoning"]:
            line += f"（含推理 {u['reasoning']:,}）"
        print(line)
        if r["cost"]:
            print(f"    估算成本 ¥{r['cost'][0]:.4f}{r['cost'][1]} ｜ 耗时 {r['duration_s']} 秒")
        else:
            print(f"    耗时 {r['duration_s']} 秒")
        if r["extra_llm"]:
            print(f"    另有 {r['extra_llm']} 次无用量记录的附加 LLM 请求（标题/搜索），成本未计入")
    print()


if __name__ == "__main__":
    main()
