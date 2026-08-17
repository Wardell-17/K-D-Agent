# -*- coding: utf-8 -*-
r"""analyze_session.py — DeepSeek Harness 会话账本分析工具（官方合并版 · 实验 005 主体）

用法（Windows）:
    python analyze_session_merged.py [目标] [--probe]

- 不传参数：全局自动发现 DSH_HOME\sessions 下"最近"的主会话（无 parentSession 且
  最后事件时间最新），并分析其全部子代理会话（parentSession 指向主会话 id）。
- 传会话目录名（如 9da9ba61-1ada-42dd-aa56-2b785a3362d7 或 session-xxxx）：在
  DSH_HOME\sessions 全局按名称查找（可在任意 cwd 运行）。
- 传路径：会话文件（取其目录）/ 会话目录 / 会话根（--D-xxx-- 层，分析其下最近一组）。
- --probe：打印事件样例核对 JSONL schema（不统计）。

合并来源:
- 旧官方版 D:\agent-project\compare\analyze_session.py（全局发现 / 多帧切帧解码 /
  chunk-usage 与 finish 块数兜底 / --probe / config.yaml 计价口径）
- 新版 harness-test2\compare\analyze_session.py（zstd 回退链含 _libs / subagent 归属
  依据与候选清单 / 工具明细与缓存拆分 / deepseek 调价峰谷逐条计价 / UTF-8 安全）

JSONL schema 关键字段（实测）:
    {"type":"session","id","createdAt","cwd","delegationDepth","agentPreset",
     ["parentSession","origin":"subagent"]}        # 会话头（第 0 行）
    {"type":"subagent/descriptor","data":{"label","agentProvider","agentModel"}}
    {"type":"turn/start"|"turn/end","data":{"turn":N}}
    {"type":"step/start"|"step/end","data":{"turn","step"}}   # 一步 = 一次主模型调用
    {"type":"request/context","data":{"provider","model"}}    # 模型声明（兜底）
    {"type":"assistant/message","data":{"message":{"source":{"provider","model"},
        "content":[{"type":"tool-call",...}]},"usage":{
        "inputTokens","outputTokens","cacheReadTokens","reasoningTokens"}}}
    {"type":"assistant/chunk","data":{"chunk":{"type":"usage"|"finish",
        "usage":{...},"replayState":{"provider","model"}}}}  # 老版本兜底来源
    {"type":"tool/call","data":{"name","arguments"}} / {"type":"tool/result"}
    {"type":"web/deepseek-search-llm-request","data":{"body":{"model"}}}  # 无 usage
    {"type":"session/title-llm-request","data":{"route":{"provider","model"}}}  # 无 usage

统计口径:
- LLM 调用 = assistant/message 数；老版本会话（无此事件）回退 assistant/chunk 的
  finish 块数。
- 工具调用 = tool/call 事件数；老版本回退 message content 中 tool-call 块数。
- tokens：输入 = inputTokens（缓存未命中）+ cacheReadTokens（缓存命中）；
  输出 = outputTokens（含 reasoningTokens，不计双份）。
  注：实测 schema 中 inputTokens 为未命中部分（9da9ba61: 44,361 + 961,280 =
  1,005,641 与验收一致）；旧版"input 含 cache"的解释与实测不符，合并时弃用。
- 成本按人民币（元/百万 tokens）逐条（每条 assistant/message 按其事件时间）匹配
  单价与峰谷系数后求和；单价无法确定输出"无法估算"（禁止编造）。

=== 单价表（人民币，元/百万 tokens；检索日期 2026-08-18）===
1) deepseek（provider 含 "deepseek"，当前模型 deepseek-v4-flash）
   - 2026-08-17 00:00（北京时间）前：缓存命中 ¥0.2 / 未命中 ¥1.0 / 输出 ¥2.0
     来源：architect-engineer/config.yaml 人工核实价（2026-07-31 公测价）。
     注：2026-08-13 公告称 8/17 前缓存命中为 ¥0.02（时代周报/东方财富），与
     config.yaml 有出入；按任务要求以 config.yaml 口径为准，此处保留原值。
   - 2026-08-17 起（官方 api-docs.deepseek.com，2026-08-17 生效）：
     空闲时段：缓存命中 ¥0.05 / 未命中 ¥1.5 / 输出 ¥4.5
     高峰时段（北京 09:00-12:00、14:00-18:00）为上述 ×2。
2) kimi（provider 含 "kimi" 或模型为 k3；当前 Kimi Code / k3）
   - 缓存命中 ¥4.0 / 未命中 ¥4.0 / 输出 ¥16.0
     来源：architect-engineer/config.yaml。Kimi Code 为订阅额度（非按 token 计费），
     金额仅为数量级估算，输出标注"（订阅估算值）"。

调试钩子：环境变量 ANALYZE_SESSION_FORCE_NO_ZSTD=1 可强制跳过所有 zstd 库加载，
用于自检"无 zstd 库环境"的报错路径（仅测试用，勿在日常使用）。
"""

import io
import json
import os
import sys
from collections import Counter
from pathlib import Path

# ---- 输出全程 UTF-8 安全（Windows 控制台可能默认 GBK）----------------------
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

DSH_HOME = Path(r"D:\agent-project\dsh-home")
SESSIONS_ROOT = DSH_HOME / "sessions"
BEIJING = __import__("datetime").timezone(__import__("datetime").timedelta(hours=8))
_V4_NEW_PRICE_EPOCH_MS = int(__import__("datetime").datetime(
    2026, 8, 17, 0, 0, 0, tzinfo=BEIJING).timestamp() * 1000)

# ===========================================================================
# 1) zstd 解码回退链：compression.zstd → site-packages zstandard → 脚本同目录 _libs
# ===========================================================================
_zstd = None
_zstd_source = None


def get_zstd():
    """加载 zstd 解码器；返回统一接口 {"decompress": f(bytes)->bytes}。"""
    global _zstd, _zstd_source
    if _zstd is not None:
        return _zstd

    attempts = []

    # 测试钩子：强制跳过所有库（仅自检回退链报错用）
    if os.environ.get("ANALYZE_SESSION_FORCE_NO_ZSTD") == "1":
        attempts.append("被 ANALYZE_SESSION_FORCE_NO_ZSTD=1 跳过")
    else:
        try:  # ① Python 3.14+ 标准库
            from compression import zstd as _c
            _zstd = {"decompress": _c.decompress, "source": "compression.zstd (Python 3.14+)"}
            _zstd_source = _zstd["source"]
            return _zstd
        except ImportError:
            attempts.append("compression.zstd（无，需 Python 3.14+）")

        try:  # ② pip 包 zstandard（site-packages）
            import zstandard as _z
            _zstd = {
                "decompress": lambda b: _z.ZstdDecompressor().stream_reader(
                    io.BytesIO(b), read_across_frames=True).read(),
                "source": "zstandard %s (site-packages)" % getattr(_z, "__version__", "?"),
            }
            _zstd_source = _zstd["source"]
            return _zstd
        except ImportError:
            attempts.append("zstandard（site-packages 无）")

        try:  # ③ 脚本同目录 _libs 的 vendored zstandard（随本脚本一起归位）
            _libs = Path(__file__).resolve().parent / "_libs"
            if not _libs.is_dir():
                raise ImportError("_libs 目录不存在: %s" % _libs)
            sys.path.insert(0, str(_libs))
            import zstandard as _z2
            _zstd = {
                "decompress": lambda b: _z2.ZstdDecompressor().stream_reader(
                    io.BytesIO(b), read_across_frames=True).read(),
                "source": "zstandard %s (_libs vendored)" % getattr(_z2, "__version__", "?"),
            }
            _zstd_source = _zstd["source"]
            return _zstd
        except ImportError:
            attempts.append("_libs vendored zstandard（%s 不存在或导入失败）" % _libs)

    raise SystemExit(
        "无法加载 zstd 解码器：\n"
        "  已尝试：%s\n"
        "  请任选其一：\n"
        "    1) 使用 Python 3.14+（标准库 compression.zstd）；\n"
        "    2) python -m pip install zstandard；\n"
        "    3) 恢复脚本同目录 _libs\\zstandard（vendored 库，随本脚本归位）。"
        % "；".join(attempts))


def decompress_bytes(b: bytes) -> bytes:
    return get_zstd()["decompress"](b)


def decode_frames(path: Path) -> list:
    """session.jsonl.zstd 由多个 zstd 帧追加而成，按魔数切帧逐段解码（逐帧容错）。"""
    buf = path.read_bytes()
    magic = b"\x28\xb5\x2f\xfd"
    pos, i = [], 0
    while True:
        j = buf.find(magic, i)
        if j < 0:
            break
        pos.append(j)
        i = j + 4
    events, frame_errs = [], 0
    for k, start in enumerate(pos):
        end = pos[k + 1] if k + 1 < len(pos) else len(buf)
        try:
            text = decompress_bytes(buf[start:end]).decode("utf-8", "replace")
        except Exception:
            frame_errs += 1
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


# ===========================================================================
# 2) 计价（人民币，元/百万 tokens）—— 以 architect-engineer/config.yaml 口径为准
# ===========================================================================
PRICES_CNY = [
    # (匹配关键字, 档位列表，每档 {"hit","miss","output","peak","since","note"})
    ("deepseek", [
        {"hit": 0.2, "miss": 1.0, "output": 2.0, "peak": None, "since": 0,
         "note": "architect-engineer/config.yaml 人工核实价（2026-07-31 公测价）"},
        {"hit": 0.05, "miss": 1.5, "output": 4.5, "peak": ((9, 12), (14, 18)),
         "since": _V4_NEW_PRICE_EPOCH_MS,
         "note": "官方调价（api-docs.deepseek.com，2026-08-17 生效）空闲时段，高峰×2（北京 09-12/14-18 点）"},
    ]),
    ("kimi", [
        {"hit": 4.0, "miss": 4.0, "output": 16.0, "peak": None, "since": 0,
         "note": "architect-engineer/config.yaml（Kimi Code 订阅额度，非按 token 计费，数量级估算值）"},
    ]),
]


def pick_price(model: str, time_ms):
    """按模型名与事件时间选档；无法确定返回 (None, 说明)。"""
    key = (model or "").lower()
    for kw, entries in PRICES_CNY:
        if kw in key:
            chosen = entries[0]
            for e in entries:
                if time_ms >= e["since"]:
                    chosen = e
            return chosen, None
    return None, "无法估算（模型 %r 无单价表，禁止编造）" % model


def peak_factor(price, time_ms):
    if not price.get("peak"):
        return 1.0
    dt = __import__("datetime").datetime.fromtimestamp(time_ms / 1000.0, BEIJING)
    for h1, h2 in price["peak"]:
        if h1 <= dt.hour < h2:
            return 2.0
    return 1.0


def cost_of(price, usage, time_ms):
    k = peak_factor(price, time_ms)
    return (usage["cache_read"] * price["hit"] * k
            + usage["input"] * price["miss"] * k
            + usage["output"] * price["output"] * k) / 1_000_000.0


# ===========================================================================
# 3) 单会话统计（新旧能力合并）
# ===========================================================================
def summarize(session_dir: Path) -> dict | None:
    f = session_dir / "session.jsonl.zstd"
    if not f.exists():
        return None
    events = decode_frames(f)
    if not events:
        return None

    # 老版本会话兜底判定：整个会话是否存在 assistant/message usage。
    # 注意不能用运行时的 saw_msg_usage 门控——新版本会话中 assistant/chunk(usage)
    # 块可能先于第一条 assistant/message 出现，运行时门控会把首条 chunk usage 重复计入。
    has_msg_usage = any(
        e.get("type") == "assistant/message"
        and ((e.get("data") or {}).get("usage")
             or ((e.get("data") or {}).get("message") or {}).get("usage"))
        for e in events)

    header = next((e for e in events if e.get("type") == "session"), {})
    descriptor = next((e.get("data") for e in events
                       if e.get("type") == "subagent/descriptor"), None)

    model_seen = None
    model_attr = Counter()          # (provider, model) -> assistant/message 次数
    route = None                    # request/context 兜底
    llm_calls = 0
    tool_calls = 0
    tool_names = Counter()
    msg_content_tool_calls = 0      # 老版本兜底：message content 里的 tool-call
    extra_llm = 0
    usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "reasoning": 0}
    usage_source = None
    chunk_usage_events = 0
    first_t = last_t = None
    turns = set()
    step_durations_ms = []
    step_starts = {}
    cost = 0.0
    cost_note = None
    unknown_cost_calls = 0

    for e in events:
        t = e.get("time")
        if t:
            first_t = t if first_t is None else min(first_t, t)
            last_t = t if last_t is None else max(last_t, t)
        etype = e.get("type", "")
        data = e.get("data") or {}

        if etype == "request/context" and data.get("provider"):
            route = "%s/%s" % (data["provider"], data.get("model", "?"))

        elif etype == "assistant/message":
            llm_calls += 1
            msg = data.get("message") or {}
            src = msg.get("source") or {}
            if src.get("provider"):
                model_seen = "%s/%s" % (src["provider"], src.get("model", "?"))
                model_attr[(src["provider"], src.get("model"))] += 1
            for c in msg.get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool-call":
                    msg_content_tool_calls += 1
            u = (data.get("usage") or msg.get("usage")) or {}
            if u:
                usage_source = "assistant/message"
                usage["input"] += u.get("inputTokens", 0)
                usage["output"] += u.get("outputTokens", 0)
                usage["cache_read"] += u.get("cacheReadTokens", 0)
                usage["cache_write"] += u.get("cacheWriteTokens", 0)
                usage["reasoning"] += u.get("reasoningTokens", 0)
                # 逐条计价：按本条事件时间匹配单价与峰谷
                model_for_price = model_seen or route or "unknown"
                price, note = pick_price(model_for_price, e.get("time") or first_t or 0)
                if price is None:
                    unknown_cost_calls += 1
                    cost_note = note
                else:
                    cost += cost_of(price, {
                        "input": u.get("inputTokens", 0),
                        "output": u.get("outputTokens", 0),
                        "cache_read": u.get("cacheReadTokens", 0),
                        "cache_write": u.get("cacheWriteTokens", 0),
                    }, e.get("time") or first_t or 0)

        elif etype == "assistant/chunk":
            chunk = data.get("chunk") or {}
            if isinstance(chunk, dict) and chunk.get("type") == "usage" and not has_msg_usage:
                u = chunk.get("usage") or {}
                usage_source = "assistant/chunk（老版本会话兜底）"
                usage["input"] += u.get("inputTokens", 0)
                usage["output"] += u.get("outputTokens", 0)
                usage["cache_read"] += u.get("cacheReadTokens", 0)
                usage["cache_write"] += u.get("cacheWriteTokens", 0)
                chunk_usage_events += 1
            if isinstance(chunk, dict) and chunk.get("type") == "finish":
                rs = chunk.get("replayState") or {}
                # 仅作 model_seen 兜底（老版本会话无 assistant/message 时显示用）；
                # 不计数 model_attr——新版本会话里 finish 块可能先于首条 message 出现，
                # 误加会使模型调用归属多计。
                if rs.get("provider") and not model_seen:
                    model_seen = "%s/%s" % (rs["provider"], rs.get("model", "?"))

        elif etype == "tool/call":
            tool_calls += 1
            tool_names[data.get("name", "?")] += 1

        elif etype in ("web/deepseek-search-llm-request", "session/title-llm-request"):
            extra_llm += 1

        elif etype == "turn/start":
            turns.add(data.get("turn"))

        elif etype == "step/start":
            step_starts[(data.get("turn"), data.get("step"))] = e.get("time")

        elif etype == "step/end":
            key = (data.get("turn"), data.get("step"))
            if key in step_starts and step_starts[key]:
                step_durations_ms.append(e.get("time") - step_starts[key])

    # 老版本会话兜底：无 assistant/message 时 finish 块数 = LLM 调用数
    if llm_calls == 0:
        llm_calls = sum(1 for e in events
                        if e.get("type") == "assistant/chunk"
                        and ((e.get("data") or {}).get("chunk") or {}).get("type") == "finish")
        if llm_calls and not has_msg_usage and usage_source is None:
            # 老版本：chunk usage 已在上述兜底分支累计；若累计非零则整会话按首事件时间算一次
            if usage["input"] or usage["output"] or usage["cache_read"]:
                price, note = pick_price(model_seen or route or "unknown", first_t or 0)
                if price is None:
                    unknown_cost_calls += 1
                    cost_note = note
                else:
                    cost = cost_of(price, usage, first_t or 0)
    # 老版本工具兜底：无 tool/call 事件时用 message content 的 tool-call 块数
    if tool_calls == 0:
        tool_calls = msg_content_tool_calls

    model = model_seen or route or "unknown"
    if unknown_cost_calls and not cost:
        cost = None
    return {
        "id": header.get("id", session_dir.name),
        "dir": session_dir.name,
        "short": session_dir.name.replace("session-", "")[:8],
        "workspace": session_dir.parent.name,
        "cwd": header.get("cwd", "?"),
        "preset": header.get("agentPreset"),
        "depth": header.get("delegationDepth", 0),
        "parent": header.get("parentSession"),
        "origin": header.get("origin"),
        "created": header.get("createdAt", 0),
        "descriptor": descriptor,
        "model": model,
        "model_attr": model_attr,
        "llm_calls": llm_calls,
        "tool_calls": tool_calls,
        "tool_names": tool_names,
        "extra_llm": extra_llm,
        "usage": usage,
        "usage_source": usage_source,
        "turns": sorted(turns),
        "steps": len(step_durations_ms),
        "step_durations_ms": step_durations_ms,
        "cost": cost,
        "cost_note": cost_note,
        "unknown_cost_calls": unknown_cost_calls,
        "duration_s": round((last_t - first_t) / 1000, 1) if first_t and last_t else 0,
        "first_t": first_t or 0,
        "last_t": last_t or 0,
    }


# ===========================================================================
# 4) 全局发现 + 归属判定
# ===========================================================================
def discover_all(root: Path):
    """返回 (主会话 dict|None, 子代理 list[(dir,sum)], 候选清单 list[str])。
    主会话：无 parentSession 且最后事件时间最新；子代理：parentSession == 主 id。
    候选：时间窗口（主会话 ±5 分钟）内但 parent 不匹配的会话。"""
    all_dirs = sorted(d for d in root.glob("*/*/") if (d / "session.jsonl.zstd").exists())
    infos = []
    for d in all_dirs:
        s = summarize(d)
        if s:
            infos.append((d, s))
    if not infos:
        return None, [], []
    mains = [(d, s) for d, s in infos if not s["parent"]]
    if not mains:
        return None, [], []
    main_d, main_s = max(mains, key=lambda x: x[1]["last_t"])  # "最近修改"按最后事件时间
    subs = [(d, s) for d, s in infos
            if d is not main_d and s["parent"] == main_s["id"]]
    lo = (main_s["first_t"] or 0) - 5 * 60 * 1000
    hi = (main_s["last_t"] or 0) + 5 * 60 * 1000
    candidates = []
    for d, s in infos:
        if d is main_d:
            continue
        if s["parent"] == main_s["id"]:
            continue
        t = s["last_t"] or s["first_t"] or 0
        if lo <= t <= hi:
            if s["parent"]:
                candidates.append("%s（工作区 %s）：时间在主会话窗口内，但 parentSession=%r 指向其他会话 → 未认定"
                                  % (d.name, s["workspace"], s["parent"]))
            else:
                candidates.append("%s（工作区 %s）：时间在主会话窗口内，但无 parentSession（独立主会话/分叉）→ 未认定"
                                  % (d.name, s["workspace"]))
    return main_s, subs, candidates


def resolve_target(arg: str, root: Path):
    """把参数解析为会话目录列表。返回 (dirs, 说明)。"""
    p = Path(arg)
    if p.is_file() and p.suffix == ".zstd":
        return [p.parent], "会话文件 → 其目录"
    if p.is_dir():
        if (p / "session.jsonl.zstd").exists():
            return [p], "会话目录"
        direct = sorted([d for d in p.iterdir()
                         if d.is_dir() and (d / "session.jsonl.zstd").exists()],
                        key=lambda d: d.stat().st_mtime)
        if direct:
            return direct, "会话根（%d 个会话，按 mtime 排序）" % len(direct)
        return [], "目录下无会话"
    # 名称查找：全局 DSH_HOME\sessions\*/<name>
    hits = sorted(root.glob("*/" + arg))
    if len(hits) == 1:
        return [hits[0]], "全局按名称唯一命中"
    if len(hits) > 1:
        return [], "名称 %r 命中多个目录：%s" % (arg, [str(h) for h in hits])
    return [], "找不到会话目录/文件/名称：%s" % arg


# ===========================================================================
# 5) 输出
# ===========================================================================
def fmt_dur(ms):
    s = ms / 1000.0
    if s < 60:
        return "%.1f 秒" % s
    m = s / 60.0
    if m < 60:
        return "%.1f 分钟" % m
    return "%.1f 小时" % (m / 60.0)


def role_of(s):
    if s["origin"] == "subagent" or s["depth"] > 0 or s["parent"]:
        label = (s["descriptor"] or {}).get("label") or ""
        return "工程师(子代理%s)" % ("：%s" % label if label else "")
    return "架构师(主会话)"


def print_session(s, indent="  "):
    print("%s[%s] %s ｜ 工作区 %s" % (indent, role_of(s), s["id"], s["workspace"]))
    if s["origin"] == "subagent" and s["descriptor"]:
        d = s["descriptor"]
        print("%s  描述: label=%s agent=%s/%s" % (indent, d.get("label"), d.get("agentProvider"), d.get("agentModel")))
    if s["created"]:
        print("%s  创建: %s" % (indent, __import__("datetime").datetime.fromtimestamp(
            s["created"] / 1000, BEIJING).strftime("%Y-%m-%d %H:%M:%S")))
    if s["first_t"] and s["last_t"]:
        t1 = __import__("datetime").datetime.fromtimestamp(s["first_t"] / 1000, BEIJING)
        t2 = __import__("datetime").datetime.fromtimestamp(s["last_t"] / 1000, BEIJING)
        active = sum(s["step_durations_ms"]) if s["step_durations_ms"] else 0
        print("%s  时间: %s -> %s ｜ 耗时: 墙上 %s，步骤活跃 %s（已完成 %d 步，%d 回合）"
              % (indent, t1.strftime("%Y-%m-%d %H:%M:%S"), t2.strftime("%Y-%m-%d %H:%M:%S"),
                 fmt_dur(s["last_t"] - s["first_t"]), fmt_dur(active),
                 s["steps"], len(s["turns"])))
    if s["model_attr"]:
        for (prov, model), n in sorted(s["model_attr"].items()):
            print("%s  模型: provider=%s model=%s（%d 次主模型调用）" % (indent, prov, model, n))
    else:
        print("%s  模型: %s" % (indent, s["model"]))
    u = s["usage"]
    print("%s  LLM 调用: %d ｜ 工具调用: %d（tool/call；老版本兜底计数则注明）｜ 明细: %s"
          % (indent, s["llm_calls"], s["tool_calls"],
             ", ".join("%s×%d" % (k, v) for k, v in s["tool_names"].most_common(8)) or "—"))
    if s["extra_llm"]:
        print("%s    + 附加 LLM 请求 %d 次（标题生成/web 搜索，无 usage 记录，成本未计入）" % (indent, s["extra_llm"]))
    print("%s  tokens: 输入 %s（缓存未命中 %s + 缓存命中 %s）｜ 输出 %s（含推理 %s）｜ 来源: %s"
          % (indent, format(u["input"] + u["cache_read"], ","), format(u["input"], ","),
             format(u["cache_read"], ","), format(u["output"], ","),
             format(u["reasoning"], ","), s["usage_source"] or "无 usage 记录"))
    if s["cost"] is None:
        print("%s  估算成本: %s" % (indent, s["cost_note"] or "无法估算"))
    else:
        note = s["cost_note"] or ""
        print("%s  估算成本: ¥%.4f%s" % (indent, s["cost"], note))
    print("")


def print_prices():
    print("单价说明（人民币，元/百万 tokens；检索日期 2026-08-18，详见脚本头部注释）:")
    for kw, entries in PRICES_CNY:
        for e in entries:
            print("  - %s：缓存命中 ¥%.3g / 未命中 ¥%.3g / 输出 ¥%.3g（%s）"
                  % (kw, e["hit"], e["miss"], e["output"], e["note"]))
    print("  - deepseek 高峰时段（北京 09-12、14-18 点）为所列价 ×2，按每条调用的事件时间逐条匹配。")
    print("")


def probe(path: Path):
    events = decode_frames(path)
    seen = set()
    n = 0
    for e in events:
        t = e.get("type", "?")
        if n < 6 or t not in seen:
            print("\n[%s] %s" % (t, json.dumps(e, ensure_ascii=False)[:900]))
            seen.add(t)
            n += 1
        if n >= 18:
            break
    print("\n… 共 %d 条事件（解码器: %s）" % (len(events), get_zstd()["source"]))


# ===========================================================================
# 6) main
# ===========================================================================
def main():
    argv = sys.argv[1:]
    want_probe = "--probe" in argv
    argv = [a for a in argv if a != "--probe"]
    get_zstd()  # 提前触发回退链，失败立即给出清晰报错

    print("=" * 72)
    print("DSH 会话成本账本（官方合并版）｜ 解码器: %s" % get_zstd()["source"])
    print("会话根目录: %s" % SESSIONS_ROOT)
    print("=" * 72)

    if want_probe:
        target = argv[0] if argv else None
        if not target:
            sys.exit("--probe 需要会话文件/目录/目录名参数")
        dirs, why = resolve_target(target, SESSIONS_ROOT)
        if not dirs:
            sys.exit(why)
        probe(dirs[0] / "session.jsonl.zstd" if (dirs[0] / "session.jsonl.zstd").exists() else dirs[0])
        return

    if not argv:
        main_s, subs, candidates = discover_all(SESSIONS_ROOT)
        if main_s is None:
            sys.exit("DSH_HOME\\sessions 下没有找到任何主会话。")
        print("\n[归属说明]")
        print("  主会话: %s（工作区 %s，依据: 无 parentSession 且最后事件时间最新 %s）"
              % (main_s["id"], main_s["workspace"],
                 __import__("datetime").datetime.fromtimestamp(
                     main_s["last_t"] / 1000, BEIJING).strftime("%Y-%m-%d %H:%M:%S")))
        for d, s in subs:
            print("  subagent: %s（工作区 %s，依据: header.parentSession == 主会话 id）" % (s["id"], s["workspace"]))
        if candidates:
            print("  候选但未认定: ")
            for c in candidates:
                print("    - %s" % c)
        rows = [main_s] + [s for _, s in subs]
        print("")
    else:
        dirs, why = resolve_target(argv[0], SESSIONS_ROOT)
        if not dirs:
            sys.exit(why)
        print("\n[目标解析] %s" % why)
        rows = [s for s in (summarize(d) for d in dirs) if s]
        rows.sort(key=lambda r: (r["depth"], r["created"]))
        subs = []
        if not rows:
            sys.exit("目标下没有可解析的会话。")

    print_prices()
    print("=" * 72)
    print("[角色账本]")
    print("")
    for s in rows:
        print_session(s)

    total_calls = sum(s["llm_calls"] for s in rows)
    total_tools = sum(s["tool_calls"] for s in rows)
    n_main = sum(1 for s in rows if not s["parent"] and s["origin"] != "subagent")
    n_sub = len(rows) - n_main
    tin = sum(s["usage"]["input"] + s["usage"]["cache_read"] for s in rows)
    tout = sum(s["usage"]["output"] for s in rows)
    costs = [s["cost"] for s in rows if s["cost"] is not None]
    unknown = [s for s in rows if s["cost"] is None]
    print("-" * 72)
    print("[汇总]")
    print("  会话数: %d（主会话 %d + 子代理 %d）｜ LLM 调用: %d ｜ 工具调用: %d"
          % (len(rows), n_main, n_sub, total_calls, total_tools))
    print("  tokens: 输入 %s（未命中 %s + 命中 %s）｜ 输出 %s"
          % (format(tin, ","), format(sum(s["usage"]["input"] for s in rows), ","),
             format(sum(s["usage"]["cache_read"] for s in rows), ","), format(tout, ",")))
    if costs:
        print("  估算成本合计: ¥%.4f%s" % (sum(costs),
              "（另有 %d 个会话无法估算）" % len(unknown) if unknown else ""))
    else:
        print("  估算成本: 无法估算（%s）" % ("；".join(s["cost_note"] for s in unknown) or "无单价"))
    print("  注: 附加 LLM 请求（标题生成/web 搜索）无 usage 记录，成本未计入；"
          "Kimi 为订阅额度，金额仅数量级参考（订阅估算值）。")
    print("=" * 72)


if __name__ == "__main__":
    main()
