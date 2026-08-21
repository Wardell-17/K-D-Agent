"""
架构师 + 工程师 多模型编排器（MVP）
=====================================
设计蓝本：《深入理解 AI Agent》（李博杰）实验 10-2 管理者模式 + 10.4.3.2 提议者-审核者范式。

核心架构决策（每条都能在书中找到依据）：
1. 不共享上下文（10.4）：架构师(Kimi K3)与工程师(DeepSeek V4-Flash)各自维护独立
   对话历史，只通过"移交包"通信——这也天然满足 K3 不可接续异源历史的约束。
2. 移交包三要素（10.4.5）：任务描述+验收标准 / 已确认事实与约束 / 产物文件引用。
3. 验证器是循环的瓶颈（10.4.3.1 Loop 工程）：子任务"是否完成"不由工程师自己宣布，
   而由可执行的验收检查（命令/测试）产出证据，架构师基于证据验收。
4. 状态栏用纯代码维护（2.6）：轮数、工具调用计数、剩余预算由 harness 计算注入，
   绝不让 LLM 统计自己的历史。
5. 强模型给规划者（Plan-and-Act, 10.4.4）：最贵最强的 K3 只做规划与验收，
   高频执行全部交给 2 元/百万 tokens 的 V4-Flash。
6. 模型层配置化（1.2.4）：模型名、端点、价格全在 config.yaml，换模型不改代码。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field, asdict
from pathlib import Path

import yaml
from openai import OpenAI

ROOT = Path(__file__).resolve().parent
CONFIG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 成本追踪（书 6.6.3：Agent 系统的成本分析；10.2：多 Agent 收益必须覆盖成本）
# ---------------------------------------------------------------------------
class CostTracker:
    """按模型分别累计 token 与费用（元），逐次调用追加写入 cost.jsonl。"""

    def __init__(self, log_path: Path):
        self.log_path = log_path
        self.records: list[dict] = []
        self._lock = threading.Lock()   # 并行模式下多线程同时记账

    def record(self, role: str, model_cfg: dict, usage) -> dict:
        # OpenAI 兼容接口的 usage；DeepSeek 会额外返回 prompt_cache_hit_tokens
        prompt = getattr(usage, "prompt_tokens", 0) or 0
        completion = getattr(usage, "completion_tokens", 0) or 0
        hit = getattr(usage, "prompt_cache_hit_tokens", 0) or 0
        miss = max(prompt - hit, 0)
        p = model_cfg["price"]
        cost = (hit * p["input_hit"] + miss * p["input_miss"]) / 1e6 \
             + completion * p["output"] / 1e6
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "role": role, "model": model_cfg["model"],
            "prompt_tokens": prompt, "cache_hit": hit,
            "completion_tokens": completion, "cost_cny": round(cost, 6),
        }
        with self._lock:
            self.records.append(rec)
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec

    def summary(self) -> str:
        by_role: dict[str, dict] = {}
        for r in self.records:
            b = by_role.setdefault(r["role"], {"calls": 0, "tokens": 0, "cost": 0.0})
            b["calls"] += 1
            b["tokens"] += r["prompt_tokens"] + r["completion_tokens"]
            b["cost"] += r["cost_cny"]
        lines = ["\n===== 成本汇总 ====="]
        total = 0.0
        for role, b in by_role.items():
            total += b["cost"]
            lines.append(f"{role:10s} 调用 {b['calls']:3d} 次 | tokens {b['tokens']:>8,} | ¥{b['cost']:.4f}")
        lines.append(f"{'合计':10s} {'':13s} {'':13s} ¥{total:.4f}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 事件流（实验 021：看板数据源——工具调用/卡片状态/验收结果实时落盘，事件溯源）
# ---------------------------------------------------------------------------
class EventLog:
    """追加写 run 目录下的 events.jsonl；仪表盘按行读取渲染。故障安全：写失败不拖垮主流程。"""

    def __init__(self, path: Path):
        self.path = path

    def emit(self, etype: str, card: str = "", **kw):
        try:
            rec = {"ts": time.strftime("%H:%M:%S"), "type": etype, "card": card, **kw}
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 模型客户端（OpenAI 兼容；各 provider 只是配置不同）
# 实验 019：模型档案（models）与角色（roles）解耦——LLM 按档案名实例化，
# 成本记账仍记角色名，换模型只改 config.yaml 不动代码。
# ---------------------------------------------------------------------------
class LLM:
    def __init__(self, profile: str, tracker: CostTracker, role: str | None = None):
        cfg = CONFIG["models"][profile]
        key = os.environ.get(cfg["api_key_env"])
        if not key:
            raise RuntimeError(f"缺少环境变量 {cfg['api_key_env']}，请先设置 API key")
        self.name = role or profile          # 账本按角色名归集
        self.profile, self.cfg = profile, cfg
        self.client = OpenAI(api_key=key, base_url=cfg["base_url"], timeout=300.0,
                             default_headers=cfg.get("headers") or None)
        self.tracker = tracker

    @classmethod
    def for_role(cls, role: str, tracker: "CostTracker") -> "LLM":
        """按角色解析模型档案（roles 注册表）；兼容旧版 config（models 直接含角色名）。"""
        prof = (CONFIG.get("roles") or {}).get(role, {}).get("model_profile")
        if not prof:
            if role in CONFIG["models"]:
                prof = role                  # 旧版配置直通
            else:
                raise RuntimeError(f"角色 '{role}' 未在 roles 注册表中登记模型档案")
        if prof not in CONFIG["models"]:
            raise RuntimeError(f"角色 '{role}' 指向的模型档案 '{prof}' 不在 models 库中")
        return cls(prof, tracker, role=role)

    def chat(self, messages: list[dict], tools: list[dict] | None = None):
        kwargs = dict(model=self.cfg["model"], messages=messages,
                      max_tokens=self.cfg.get("max_tokens", 8192))
        if tools:
            kwargs["tools"] = tools
        resp = self.client.chat.completions.create(**kwargs)
        if getattr(resp, "usage", None):
            self.tracker.record(self.name, self.cfg, resp.usage)
        return resp.choices[0].message


def ask_json(llm: LLM, system: str, user: str) -> dict:
    """让模型输出 JSON 并解析；失败则重试一次并要求只输出 JSON。"""
    for attempt in range(2):
        msg = llm.chat([{"role": "system", "content": system},
                        {"role": "user", "content": user}])
        text = msg.content or ""
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        user = "你的上一次输出不是合法 JSON。请只输出一个 JSON 对象，不要任何解释。\n" + text[:500]
    raise RuntimeError(f"{llm.name} 连续两次未能输出合法 JSON")


# ---------------------------------------------------------------------------
# 移交包（书 10.4.5：任务描述 / 已确认事实与约束 / 产物引用）
# ---------------------------------------------------------------------------
@dataclass
class HandoffPacket:
    task_id: str
    goal: str                        # 这个子任务要做什么
    acceptance: list[str]            # 验收标准（可执行检查命令或明确判据）
    confirmed_facts: list[str] = field(default_factory=list)   # 已确认的事实与约束
    artifact_refs: list[str] = field(default_factory=list)     # 相关文件路径（引用而非内容）
    remaining_budget: int = 12       # 剩余 ReAct 轮数预算（budget-aware, 书10.2）
    visited: list[str] = field(default_factory=list)           # 循环检测
    depends_on: list[str] = field(default_factory=list)        # 前置任务卡 id（并行调度用）


# ---------------------------------------------------------------------------
# 任务卡 v0.1（卡片驱动：Markdown + YAML frontmatter，状态由代码维护流转）
# 卡片是跨角色的持久化共享状态：架构师建卡 → 工程师执行 → 编排器记账/验收 → 状态回写。
# ---------------------------------------------------------------------------
@dataclass
class TaskCard:
    task_id: str
    title: str
    goal: str
    acceptance: list[str]
    confirmed_facts: list[str] = field(default_factory=list)
    artifact_refs: list[str] = field(default_factory=list)
    status: str = "todo"          # todo / doing / done / rework / escalated
    owner: str = "architect"
    created: str = ""
    updated: str = ""
    depends_on: list[str] = field(default_factory=list)  # 前置卡 id，全部 done 才可调度
    report: str = ""              # 结构化回报（工程师 finish 后由编排器填入）
    notes: list[str] = field(default_factory=list)  # 返工指令等追加记录
    search_backend: str = ""      # 检索后端路由：""=跟随全局配置；可填 auto/tavily/ddg/deepseek
    budget: int = 0               # ReAct 轮数预算：0=跟随全局默认；深读类任务人工审卡时可加到 20

    FRONT_KEYS = ("id", "title", "status", "owner", "created", "updated", "depends_on")

    def render(self) -> str:
        def esc(s: str) -> str:
            # YAML 双引号标量：反斜杠是转义符（\a \p 等会炸 ScannerError），必须先转义
            return s.replace("\\", "\\\\").replace('"', "'").replace("\n", " ")
        deps = "[" + ", ".join(f'"{esc(d)}"' for d in self.depends_on) + "]"
        fm = [f'id: "{esc(self.task_id)}"', f'title: "{esc(self.title)}"',
              f'status: "{self.status}"', f'owner: "{self.owner}"',
              f'created: "{self.created}"', f'updated: "{self.updated}"',
              f'depends_on: {deps}']
        if self.search_backend:
            fm.append(f'search_backend: "{esc(self.search_backend)}"')
        if self.budget:
            fm.append(f'budget: {int(self.budget)}')
        acc = "\n".join(f"- {a}" for a in self.acceptance) or "- （无）"
        facts = "\n".join(f"- {f}" for f in self.confirmed_facts) or "- （无）"
        refs = "\n".join(f"- {r}" for r in self.artifact_refs) or "- （无）"
        notes = "\n".join(f"- {n}" for n in self.notes) or "- （无）"
        return ("---\n" + "\n".join(fm) + "\n---\n\n"
                f"# 任务卡 {self.task_id}：{self.title}\n\n"
                f"## 目标\n\n{self.goal}\n\n"
                f"## 验收标准\n\n{acc}\n\n"
                f"## 已确认事实与约束\n\n{facts}\n\n"
                f"## 产物引用\n\n{refs}\n\n"
                f"## 结构化回报\n\n{self.report or '（待工程师完成后填写）'}\n\n"
                f"## 返工与备注\n\n{notes}\n")

    def save(self, tasks_dir: Path) -> Path:
        tasks_dir.mkdir(parents=True, exist_ok=True)
        p = tasks_dir / f"card-{self.task_id}.md"
        p.write_text(self.render(), encoding="utf-8")
        return p

    def touch(self, status: str | None = None, owner: str | None = None):
        if status:
            self.status = status
        if owner:
            self.owner = owner
        self.updated = time.strftime("%Y-%m-%dT%H:%M:%S")


def _section(body: str, name: str) -> str:
    """取 Markdown 正文中 '## name' 到下一个 '## ' 之间的内容。"""
    m = re.search(rf"^##\s+{re.escape(name)}\s*\n(.*?)(?=^##\s|\Z)", body,
                  re.MULTILINE | re.DOTALL)
    return m.group(1).strip() if m else ""


def _bullets(body: str, name: str) -> list[str]:
    return [ln[2:].strip() for ln in _section(body, name).splitlines()
            if ln.strip().startswith("- ") and "（无）" not in ln]


def load_card(path: Path) -> tuple[HandoffPacket, TaskCard]:
    """解析任务卡（Markdown + YAML frontmatter）→ 移交包 + 卡片对象（--card 模式入口）。"""
    text = Path(path).read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not m:
        raise ValueError(f"不是合法任务卡（缺 frontmatter）: {path}")
    fm = yaml.safe_load(m.group(1)) or {}
    body = m.group(2)
    goal = _section(body, "目标")
    if not goal:
        raise ValueError(f"任务卡缺少 ## 目标 一节: {path}")
    deps = [str(d) for d in (fm.get("depends_on") or [])]
    budget = int(fm.get("budget") or 0)
    packet = HandoffPacket(
        task_id=str(fm.get("id", Path(path).stem.replace("card-", ""))),
        goal=goal,
        acceptance=_bullets(body, "验收标准"),
        confirmed_facts=_bullets(body, "已确认事实与约束"),
        artifact_refs=_bullets(body, "产物引用"),
        depends_on=deps,
    )
    if budget > 0:
        packet.remaining_budget = budget   # 卡级预算覆盖全局默认（015：深读类任务 12 轮不够）
    card = TaskCard(task_id=packet.task_id, title=str(fm.get("title", goal[:40])),
                    goal=goal, acceptance=packet.acceptance,
                    confirmed_facts=packet.confirmed_facts,
                    artifact_refs=packet.artifact_refs,
                    status=str(fm.get("status", "todo")),
                    owner=str(fm.get("owner", "human")),
                    created=str(fm.get("created", "")),
                    updated=str(fm.get("updated", "")),
                    depends_on=deps,
                    report=_section(body, "结构化回报"),
                    notes=_bullets(body, "返工与备注"),
                    search_backend=str(fm.get("search_backend", "") or ""),
                    budget=budget)
    return packet, card


# ---------------------------------------------------------------------------
# 联网检索（可插拔后端：Tavily 主力 → DuckDuckGo 免费降级；直连失败自动走本地代理）
# 设计约束：返回结构化"标题+URL+摘要"，证据优先官方域名；调用计入工具计数。
# ---------------------------------------------------------------------------
def _http_json(url: str, payload: dict | None, timeout: int = 20) -> tuple[int, str]:
    """最小 HTTP 封装：先直连，失败后走本地代理（Clash 7890）。返回 (状态码, 响应体)。"""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "Mozilla/5.0"})
    for proxy in (None, "http://127.0.0.1:7890"):
        try:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy, "https": proxy}) if proxy
                else urllib.request.ProxyHandler({}))
            with opener.open(req, timeout=timeout) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")[:2000]
        except Exception:
            continue
    return -1, "网络不可达（直连与代理均失败）"


# ── 检索驱动（可插拔 driver，实验 014：后端按任务卡路由，不再绑死单一工具）──
# 每个 driver 返回 str；返回 None 表示"本驱动不可用/无结果"，由调度策略决定降级。
# 时效性纪律（实验 013 教训）：驱动只负责取数，"查询词带时间约束"由任务卡/Prompt 层保证。

def _search_tavily(query: str, max_results: int) -> str | None:
    """Tavily（付费，1000 次/月免费档，成本可审计）。无 key / 额度耗尽 / 无结果 → None。"""
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        return None
    code, body = _http_json("https://api.tavily.com/search", {
        "api_key": key, "query": query, "max_results": max_results,
        "search_depth": "basic", "include_answer": False})
    if code == 200:
        try:
            results = json.loads(body).get("results", [])
            if results:
                lines = [f"[Tavily] 查询: {query}"]
                for i, r in enumerate(results, 1):
                    lines.append(f"{i}. {r.get('title', '')}\n   {r.get('url', '')}\n"
                                 f"   {(r.get('content') or '')[:300]}")
                return "\n".join(lines)
        except json.JSONDecodeError:
            pass
        return None
    if code in (429, 432):
        return None  # 额度耗尽 → 降级
    return f"[Tavily] HTTP {code}: {body[:300]}"


def _search_ddg(query: str, max_results: int) -> str | None:
    """DuckDuckGo HTML（免费无 key，零成本兜底）。失败/无结果 → None。
    ⚠ 实验 014 实测（2026-08-18）：DDG html/lite 端点对数据中心 IP 返回
    HTTP 202 反爬拦截页，Bing 直连/代理均返回机器人填充页——免费 HTML 抓取
    在当前网络环境已不可用，此驱动仅作占位，auto 链实际等于 tavily-only。"""
    q = urllib.parse.quote(query)
    code, body = _http_json(f"https://html.duckduckgo.com/html/?q={q}", None)
    if code == 200:
        links = re.findall(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', body)
        if links:
            lines = [f"[DuckDuckGo] 查询: {query}"]
            for i, (url, title) in enumerate(links[:max_results], 1):
                title = re.sub(r"<[^>]+>", "", title).strip()
                lines.append(f"{i}. {title}\n   {url}")
            return "\n".join(lines)
    return None


def _search_deepseek(query: str, max_results: int) -> str | None:
    """DeepSeek 服务端联网（实验性）。官方公开 API 暂无检索能力，此驱动走
    自建兼容端点：需设 DEEPSEEK_SEARCH_BASE_URL / DEEPSEEK_SEARCH_MODEL 环境变量。
    实验 013 已证明该后端对国内政务/行业数据的时效性最强，但用量计费不可审计，
    仅在对时效性要求极高的任务卡上显式启用。"""
    base = os.environ.get("DEEPSEEK_SEARCH_BASE_URL")
    model = os.environ.get("DEEPSEEK_SEARCH_MODEL", "deepseek-v4-flash")
    if not base:
        return ("[deepseek-search] 未配置：请设置 DEEPSEEK_SEARCH_BASE_URL "
                "（指向带服务端联网的兼容端点）。公开 api.deepseek.com 不提供检索，"
                "请改用 tavily / ddg 后端。")
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    code, body = _http_json(base.rstrip("/") + "/chat/completions", {
        "model": model,
        "messages": [{"role": "user", "content":
                      f"联网检索以下问题，返回 {max_results} 条以内结果，"
                      f"每条含：标题 / URL / 数据发布时间（精确到年月）/ 一句话摘要。\n查询：{query}"}],
        "max_tokens": 2000})
    if code == 200:
        try:
            content = json.loads(body)["choices"][0]["message"]["content"]
            return f"[deepseek-search 实验性·用量不可审计] 查询: {query}\n{content}"
        except (json.JSONDecodeError, KeyError, IndexError):
            pass
    return f"[deepseek-search] HTTP {code}: {body[:300]}"


SEARCH_DRIVERS = {"tavily": _search_tavily, "ddg": _search_ddg,
                  "deepseek": _search_deepseek}
SEARCH_FALLBACK = ("tavily", "ddg")   # auto 模式的降级链


def web_search(query: str, max_results: int = 5, backend: str = "auto") -> str:
    """可插拔检索入口。backend: auto（tavily→ddg 降级）或 SEARCH_DRIVERS 中的具体驱动名。"""
    if backend == "auto":
        for name in SEARCH_FALLBACK:
            out = SEARCH_DRIVERS[name](query, max_results)
            if out:
                return out
        return "检索失败：auto 降级链（tavily→ddg）均不可用"
    driver = SEARCH_DRIVERS.get(backend)
    if not driver:
        return f"错误：未知检索后端 '{backend}'，可选: auto / {', '.join(SEARCH_DRIVERS)}"
    out = driver(query, max_results)
    if out:
        return out
    # 指定后端无结果 → 兜底提示（不擅自跨后端，保持路由可预期、账本可归因）
    return (f"[{backend}] 无结果或不可用。如需降级，请在任务卡把 search_backend 改为 auto，"
            f"或换一个查询词重试。")


# ---------------------------------------------------------------------------
# 工程师工具集（约束：故障安全默认值——只能在工作目录内读写，命令有黑名单）
# ---------------------------------------------------------------------------
class Toolbox:
    def __init__(self, workdir: Path, allowed_tools: list[str] | None = None):
        self.workdir = workdir.resolve()
        self.allowed_tools = set(allowed_tools) if allowed_tools else None  # 角色级工具白名单
        self.call_counts: dict[str, int] = {}
        ecfg = CONFIG["engineer_tools"]
        self.allow_cmd = ecfg["allow_run_command"]
        self.allow_search = ecfg.get("allow_web_search", True)
        self.search_backend = str(ecfg.get("search_backend", "auto"))  # 可被任务卡覆盖
        # 只读的额外根目录（实验 015：读外部源码仓库等场景；写入仍严格限于工作目录）
        self.extra_roots = [str(Path(r).resolve())
                            for r in ecfg.get("extra_read_roots", [])]
        self.cmd_timeout = ecfg["command_timeout_sec"]
        self.deny = [re.compile(p) for p in ecfg["command_deny_patterns"]]
        self.search_history: set[str] = set()   # 查询去重，防烧检索额度
        self.written: list[str] = []            # 实际写过的文件（供预算耗尽时取证）
        self.events: EventLog | None = None     # 实验 021：看板事件流（可选挂载）
        self.card_id: str = ""

    def _safe(self, rel: str) -> Path:
        p = (self.workdir / rel).resolve()
        if not str(p).startswith(str(self.workdir)):
            raise PermissionError(f"路径越界被拒绝: {rel}")
        return p

    def _safe_read(self, rel: str) -> Path:
        """读文件专用：工作目录内 或 声明过的只读根目录内（绝对路径）。"""
        p = Path(rel)
        if p.is_absolute():
            rp = str(p.resolve())
            for root in [str(self.workdir)] + self.extra_roots:
                if rp.startswith(root):
                    return p.resolve()
            raise PermissionError(f"读取越界被拒绝（不在工作目录或只读根内）: {rel}")
        return self._safe(rel)

    def count(self, name: str):
        self.call_counts[name] = self.call_counts.get(name, 0) + 1

    def status_bar(self, remaining: int) -> str:
        # 书 2.6：状态栏由代码维护，注入上下文末尾，模型"瞥一眼"即可
        counts = ", ".join(f"{k}×{v}" for k, v in self.call_counts.items()) or "无"
        return (f"<agent_status>\n剩余轮数预算: {remaining}\n"
                f"工具调用计数: {counts}\n工作目录: {self.workdir}\n</agent_status>")

    def definitions(self) -> list[dict]:
        def fn(name, desc, props, required):
            return {"type": "function", "function": {
                "name": name, "description": desc,
                "parameters": {"type": "object", "properties": props, "required": required}}}
        tools = [
            fn("read_file", "读取工作目录中的文件内容。单次最多返回 20000 字符；"
               "文件被截断时会提示总长度，用 offset 参数翻页续读",
               {"path": {"type": "string"},
                "offset": {"type": "integer", "description": "从第几个字符开始读，默认 0；"
                           "用于翻页读超大文件（如 offset=20000 读第二页）"}}, ["path"]),
            fn("write_file", "把内容写入工作目录中的文件（自动创建父目录）",
               {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
            fn("list_dir", "列出工作目录（或子目录）下的文件",
               {"path": {"type": "string", "description": "相对路径，默认 ."}}, []),
        ]
        if self.allow_search:
            tools.append(
                fn("web_search", f"联网检索（当前后端: {self.search_backend}）。"
                   "用于查证外部事实/最新资料；结果含标题+URL+摘要。"
                   "纪律：查询词带时间约束（如「2026年最新」）以保证时效性；"
                   "结论必须附来源 URL，优先官方域名；"
                   "同一查询不要重复检索，检索结果及时落盘保存",
                   {"query": {"type": "string"},
                    "max_results": {"type": "integer", "description": "默认 5，最大 10"}},
                   ["query"]))
        tools.append(
            fn("finish", "子任务完成时调用，提交结构化总结（不代表已验收）",
               {"summary": {"type": "string", "description": "做了什么、改了哪些文件、已知风险"}},
               ["summary"]))
        if self.allow_cmd:
            tools.insert(3, fn("run_command",
                               "在工作目录中执行 shell 命令（有超时与黑名单限制），用于运行测试/脚本",
                               {"command": {"type": "string"}}, ["command"]))
        if self.allowed_tools is not None:   # 实验 020：角色级工具白名单（finish 永远放行）
            allow = self.allowed_tools | {"finish"}
            tools = [t for t in tools if t["function"]["name"] in allow]
        return tools

    def execute(self, name: str, args: dict) -> str:
        self.count(name)
        if self.events:  # 调用即记录（不论成败），供看板"执行心跳"区渲染
            brief = json.dumps(args, ensure_ascii=False)
            self.events.emit("tool", self.card_id, tool=name, args=brief[:80])
        try:
            if name == "read_file":
                full = self._safe_read(args["path"]).read_text(encoding="utf-8")
                off = max(0, int(args.get("offset", 0) or 0))
                chunk = full[off:off + 20000]
                if off >= len(full) and len(full) > 0:
                    return f"提示：offset={off} 已超出文件总长 {len(full)} 字符，无内容"
                note = (f"[文件共 {len(full)} 字符，本次返回 {off}~{off + len(chunk)}"
                        + (f"，剩余 {len(full) - off - len(chunk)} 字符可用 offset 续读]"
                           if off + len(chunk) < len(full) else "，已到文件末尾]"))
                return note + "\n" + chunk
            if name == "list_dir":
                p = self._safe_read(args.get("path", "."))
                return "\n".join(sorted(x.name for x in p.iterdir())) or "(空目录)"
            if name == "write_file":
                p = self._safe(args["path"])
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(args["content"], encoding="utf-8")
                self.written.append(str(p.relative_to(self.workdir)))
                return f"已写入 {p}（{len(args['content'])} 字符）"
            if name == "list_dir":
                p = self._safe_read(args.get("path", "."))
                return "\n".join(sorted(x.name for x in p.iterdir())) or "(空目录)"
            if name == "web_search":
                q = str(args.get("query", "")).strip()
                if not q:
                    return "错误：query 不能为空"
                if q in self.search_history:
                    return "提示：该查询已检索过，结果请查阅之前的返回；避免重复烧额度"
                self.search_history.add(q)
                mr = max(1, min(int(args.get("max_results", 5)), 10))
                return web_search(q, mr, self.search_backend)
            if name == "run_command":
                cmd = args["command"]
                if any(d.search(cmd) for d in self.deny):
                    return "错误：命令命中安全黑名单，已拒绝执行"
                r = subprocess.run(cmd, shell=True, cwd=self.workdir,
                                   capture_output=True, text=True,
                                   timeout=self.cmd_timeout, encoding="utf-8", errors="replace")
                out = (r.stdout + r.stderr).strip()
                return f"exit={r.returncode}\n{out[:8000]}"
            return f"错误：未知工具 {name}"
        except Exception as e:  # 纠正机制：错误以文本形式回传，让模型自我恢复
            return f"工具执行异常: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# 工程师：DeepSeek V4-Flash，独立上下文 + ReAct 循环
# ---------------------------------------------------------------------------
ENGINEER_SYS = """你是一名执行工程师。你收到一个结构化的任务移交包（JSON），包含：
goal（要做什么）、acceptance（验收标准）、confirmed_facts（已确认的事实与约束）、
artifact_refs（相关文件路径，需自行读取）。

工作纪律：
1. 先读 artifact_refs 里的相关文件，再动手；大文件单次只返回 20000 字符——
   若返回头提示有剩余，说明只读了前半截，关键逻辑可能在后半段，
   必须用 offset 参数翻页读完再下结论，禁止凭半截文件臆测全貌；
2. 每完成一步用 run_command 实际验证（跑测试/脚本），不要凭感觉声明完成；
3. 遇到命令失败，读错误输出、修复、重试；同一错误连续两次则换方案；
4. 只写本任务目标内的文件；其他任务可能并行进行，绝不改动卡片未授权你写的共享文件
   （跨任务成果的组装是"集成卡"的职责，不是你的）；
5. 需要外部事实/最新资料时用 web_search 检索查证，禁止凭训练记忆编造；
   查询词必须带时间约束（如「2026年最新」「截至2026」）以避免抓到过期口径；
   结论必须附来源 URL（优先官方域名）与数据发布时间（精确到年月），
   检索结果及时 write_file 落盘（如 research/ 目录）供下游任务引用；
6. 完成后调用 finish 提交结构化总结，必须包含四块：改动文件清单 / 实际运行的命令 /
   命令输出摘要 / 已知风险。finish 是"我做完了一步"，最终验收由架构师基于
   实际执行结果判定，不由你宣布。"""


def role_prompt(role: str, key: str, fallback: str) -> str:
    """实验 020：角色的系统提示词来自 prompts/ 目录（config 声明路径），
    文件缺失时回落到代码内置版本——改提示词 = 改 .md 文件，不动 Python。"""
    rel = (CONFIG.get("roles") or {}).get(role, {}).get(key)
    if rel:
        f = ROOT / rel
        if f.exists():
            return f.read_text(encoding="utf-8")
    return fallback


def run_engineer(packet: HandoffPacket, workdir: Path, llm: LLM,
                 search_backend: str = "", system_prompt: str | None = None,
                 allowed_tools: list[str] | None = None,
                 events: EventLog | None = None, card_id: str = "") -> dict:
    tb = Toolbox(workdir, allowed_tools=allowed_tools)
    tb.events, tb.card_id = events, card_id
    if search_backend:   # 任务卡级路由覆盖全局默认（实验 014：后端可插拔）
        tb.search_backend = search_backend
    messages = [
        {"role": "system", "content": system_prompt or ENGINEER_SYS},
        {"role": "user", "content": "任务移交包：\n" + json.dumps(asdict(packet), ensure_ascii=False, indent=2)},
    ]
    budget = packet.remaining_budget
    text_only_streak = 0
    while budget > 0:
        # 状态栏注入（代码维护，不占用 LLM 统计）
        msgs = messages + ([{"role": "user", "content": tb.status_bar(budget)}]
                           if CONFIG["logging"]["status_bar"] else [])
        msg = llm.chat(msgs, tools=tb.definitions())
        messages.append({"role": "assistant", "content": msg.content or "",
                         **({"tool_calls": [tc.model_dump() for tc in msg.tool_calls]}
                            if msg.tool_calls else {})})
        if not msg.tool_calls:
            text_only_streak += 1
            # 连续两次纯文字回复：视为"做完了但没打卡"，以最后一段文字为总结收尾
            # （反正最终判定权在验证器+架构师，不以它的自述为准）
            if text_only_streak >= 2:
                return {"status": "finished_implicit",
                        "summary": (msg.content or "")[:2000],
                        "tool_calls": tb.call_counts, "written_files": tb.written}
            messages.append({"role": "user", "content":
                "如果你已完成本任务，请调用 finish 工具提交结构化总结；"
                "如果还没完成，请继续用工具推进。"})
            budget -= 1
            continue
        text_only_streak = 0
        for tc in msg.tool_calls:
            name = tc.function.name
            args = json.loads(tc.function.arguments or "{}")
            if name == "finish":
                return {"status": "finished", "summary": args.get("summary", ""),
                        "tool_calls": tb.call_counts, "written_files": tb.written}
            result = tb.execute(name, args)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
        budget -= 1
    return {"status": "budget_exhausted", "summary": "轮数预算耗尽",
            "tool_calls": tb.call_counts, "written_files": tb.written}


# ---------------------------------------------------------------------------
# 验证器（Loop 工程核心：完成的判定来自真实执行，不来自模型宣称）
# ---------------------------------------------------------------------------
def verify(packet: HandoffPacket, workdir: Path) -> dict:
    """执行 acceptance 中的 shell 检查（以 '!' 开头的条目），其余条目留给架构师评判。"""
    evidence, ok = [], True
    for item in packet.acceptance:
        if item.startswith("!"):
            cmd = item[1:].strip()
            try:
                r = subprocess.run(cmd, shell=True, cwd=workdir, capture_output=True,
                                   text=True, timeout=CONFIG["engineer_tools"]["command_timeout_sec"],
                                   encoding="utf-8", errors="replace")
                passed = r.returncode == 0
                evidence.append({"check": cmd, "passed": passed,
                                 "output": (r.stdout + r.stderr).strip()[:3000]})
                ok = ok and passed
            except Exception as e:
                evidence.append({"check": cmd, "passed": False, "output": str(e)})
                ok = False
    return {"all_passed": ok, "evidence": evidence}


# ---------------------------------------------------------------------------
# 架构师：Kimi K3，只做两件事——拆任务、基于证据验收
# ---------------------------------------------------------------------------
ARCHITECT_PLAN_SYS = """你是首席架构师。把用户的任务拆解为 1-5 个可独立执行、可验证的子任务。
只输出 JSON：{"subtasks": [{"task_id": "t1", "goal": "...",
"acceptance": ["以!开头的是可执行验收命令，如 !python test.py；其余为文字判据"],
"confirmed_facts": ["执行者必须遵守的约束与已知事实"],
"artifact_refs": ["相关文件路径"], "remaining_budget": 12,
"depends_on": ["可选：本任务依赖的前置 task_id，无依赖则省略或给空数组"]}]}
原则：每个子任务必须有客观验收标准；事实与约束写全，执行者看不到本次对话。
信息保真纪律（最高优先级）：goal 必须完整保留用户任务中的全部具体要求——
专有名词、数字、日期、交付格式、每一条点名的事项，禁止概括性转述导致信息丢失。
用户说"三条事实：1)X 2)Y 3)Z"，卡里就必须逐字出现 X/Y/Z，不能只写"三条事实"。
相互独立的子任务不要加依赖（系统会并行执行）；只有真正需要前序产物时才填 depends_on。
文件隔离纪律（防并行写冲突）：相互并行的子任务必须写各自独立的文件，禁止写同一文件；
若多个子任务的成果需要汇入同一文件，必须单独拆出一个"集成"子任务（depends_on 各产出卡），
由它串行完成组装——共享文件的写入永远收敛到串行卡点。
动态拆分纪律（自主决定员工数量）：
- 粒度判据：每个子任务必须"聚焦单一可独立验收的模块"，且能写出可执行的验收命令；
  若一张卡写不出明确验收命令，说明拆得不对（太大或太虚）。
- 并行员工数量由你自主权衡：太少会导致单卡超复杂、执行失败返工烧钱；太多会导致
  管理开销与集成难度爆炸。一般 2-5 个并行执行卡为宜。
- 强制集成卡协议：当拆分出 N>1 个并行执行卡且它们的成果需要汇入同一入口文件时，
  必须额外生成第 N+1 张集成卡（depends_on 全部 N 张执行卡）；集成卡职责仅限 import
  与组装，禁止编写业务逻辑。
重要：运行环境是 Windows（cmd.exe，无 Unix 命令）。验收命令只能用 python、
Windows 原生命令（dir/type）或 python -c 一行流；严禁 test/grep/cat/ls 等 Unix 命令。
涉及中文内容匹配的验收检查一律用 python（findstr 在 GBK 代码页下匹配 UTF-8 中文必失败）。"""

ARCHITECT_REVIEW_SYS = """你是首席架构师，正在验收工程师的工作。你会看到：
移交包、工程师自述的总结、以及验证器对验收命令的真实执行结果（证据）。
规则：证据失败则必须返工；工程师的总结只是自述，不能当作完成证明。
若 payload 含 process_note（工程师未走 finish 流程，如预算耗尽/隐式收尾）：
仅以验证器证据与实际落盘产物判定达标与否——产物达标则 pass 并在 reason 注明
"流程收尾缺失但产物达标"；产物不达标才 rework。不因流程缺失本身否决。
只输出 JSON：{"verdict": "pass" 或 "rework", "reason": "...", 
"fix_instructions": "若 rework，给工程师的具体修复指令" }"""


class Orchestrator:
    def __init__(self, task: str, run_dir: Path | None = None):
        self.task = task
        # resume 模式复用既有 run 目录（断点续跑），否则按时间戳新建
        self.run_dir = Path(run_dir) if run_dir else \
            ROOT / CONFIG["logging"]["dir"] / time.strftime("%Y%m%d-%H%M%S")
        self.resuming = run_dir is not None
        self.workdir = self.run_dir / "workspace"   # 产物区（工程师的工作目录）
        self.workdir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "handoffs").mkdir(exist_ok=True)
        self.tasks_dir = self.run_dir / "tasks"     # 任务卡目录（卡片驱动）
        self.tasks_dir.mkdir(exist_ok=True)
        self.cards: dict[str, TaskCard] = {}
        self.tracker = CostTracker(self.run_dir / "cost.jsonl")
        self.events = EventLog(self.run_dir / "events.jsonl")   # 实验 021：看板事件流
        self.architect = LLM.for_role("architect", self.tracker)
        self.engineer = LLM.for_role("engineer", self.tracker)

    def log_handoff(self, name: str, payload: dict):
        (self.run_dir / "handoffs" / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def run(self, plan_only: bool = False) -> dict:
        print(f"[run] 目录: {self.run_dir}")
        # 1. 架构师拆任务
        plan = ask_json(self.architect, role_prompt("architect", "prompt_plan",
                        ARCHITECT_PLAN_SYS), f"用户任务：{self.task}")
        self.log_handoff("plan.json", plan)
        subtasks = plan.get("subtasks", [])
        print(f"[architect] 拆解为 {len(subtasks)} 个子任务")

        results = []
        packets: dict[str, tuple[HandoffPacket, TaskCard]] = {}
        for st in subtasks:
            packet = HandoffPacket(**{k: v for k, v in st.items() if k in HandoffPacket.__dataclass_fields__})
            # 落任务卡：架构师拆出子任务即建卡（todo）
            card = TaskCard(task_id=packet.task_id, title=packet.goal[:40],
                            goal=packet.goal, acceptance=packet.acceptance,
                            confirmed_facts=list(packet.confirmed_facts),
                            artifact_refs=list(packet.artifact_refs),
                            created=time.strftime("%Y-%m-%dT%H:%M:%S"),
                            updated=time.strftime("%Y-%m-%dT%H:%M:%S"),
                            depends_on=list(packet.depends_on),
                            # 架构师的预算决策落卡（非默认档才写 frontmatter），
                            # 保证 --plan-only 审卡可见、--cards 重载不丢（Gemini 审出）
                            budget=packet.remaining_budget if packet.remaining_budget != 12 else 0)
            card.save(self.tasks_dir)
            self.cards[packet.task_id] = card
            self.events.emit("card_status", packet.task_id, status="todo", owner="architect")
            packets[packet.task_id] = (packet, card)
            print(f"\n--- 子任务 {packet.task_id}: {packet.goal[:60]}"
                  + (f"（依赖: {', '.join(packet.depends_on)}）" if packet.depends_on else ""))
            print(f"[card] {self.tasks_dir / ('card-' + packet.task_id + '.md')}")
        # 看板发卡台的预算滑块：KD_FORCE_BUDGET 环境变量强制覆盖全部子任务预算（021）
        force_budget = int(os.environ.get("KD_FORCE_BUDGET") or 0)
        if force_budget > 0:
            for packet, card in packets.values():
                packet.remaining_budget = force_budget
                card.budget = force_budget
                card.notes.append(f"预算由看板滑块指定: {force_budget} 轮")
                card.save(self.tasks_dir)
        if plan_only:
            # 审批门（plan-approve gate）：拆卡落盘后即停，人审卡/改卡后再用 --cards 放行
            print(f"\n[plan-only] 已生成 {len(packets)} 张任务卡，未执行。")
            print(f"[plan-only] 请审阅/修改: {self.tasks_dir}")
            print(f"[plan-only] 确认无误后放行: python orchestrator.py --cards \"{self.tasks_dir}\"")
            return {"task": self.task, "plan_only": True,
                    "cards": [str(self.tasks_dir / f"card-{tid}.md") for tid in packets],
                    "run_dir": str(self.run_dir)}
        return self._finish(self._schedule(packets))

    def _schedule(self, packets: dict[str, tuple[HandoffPacket, TaskCard]],
                  pre_done: set[str] | None = None) -> list:
        """依赖感知并行调度器：depends_on 全部 done 的卡立即派发，线程池并行执行。
        前置卡失败/升级 → 依赖它的卡冻结为 escalated（不浪费 token 跑必败任务）。
        pre_done：断点续跑时已完成的卡 id 集，视为依赖已满足且不重复执行。"""
        max_workers = CONFIG.get("parallel", {}).get("max_workers", 3)
        results: list[dict] = []
        done: set[str] = set(pre_done or set())
        failed: set[str] = set()
        pending = dict(packets)
        futures: dict = {}
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            while pending or futures:
                # 1. 派发所有依赖已就绪的卡
                for tid in [t for t, (p, c) in pending.items()
                            if all(d in done for d in p.depends_on)]:
                    if any(d in failed for d in pending[tid][0].depends_on):
                        continue  # 有失败依赖的留给下面冻结逻辑
                    packet, card = pending.pop(tid)
                    futures[pool.submit(self._execute_packet, packet, card)] = tid
                    self.events.emit("dispatch", tid,
                                     depends_on=",".join(packet.depends_on) or "无")
                # 2. 冻结：有依赖失败的卡不执行，直接升级人工
                for tid in [t for t, (p, c) in pending.items()
                            if any(d in failed for d in p.depends_on)]:
                    packet, card = pending.pop(tid)
                    card.touch(status="escalated", owner="human")
                    card.notes.append("前置任务失败/升级，本卡冻结: "
                                      + ", ".join(d for d in packet.depends_on if d in failed))
                    card.save(self.tasks_dir)
                    self.events.emit("card_status", tid, status="escalated", owner="human",
                                     reason="前置失败冻结")
                    results.append({"task_id": tid, "verdict": "escalated",
                                    "reason": "前置任务失败，依赖链冻结"})
                    failed.add(tid)
                if not futures:
                    if pending:  # 依赖成环或引用了不存在的卡
                        for tid, (packet, card) in pending.items():
                            card.touch(status="escalated", owner="human")
                            card.notes.append("依赖无法满足（成环或缺失）: "
                                              + ", ".join(packet.depends_on))
                            card.save(self.tasks_dir)
                            results.append({"task_id": tid, "verdict": "escalated",
                                            "reason": "依赖成环或缺失"})
                        pending.clear()
                    break
                # 3. 等任意一张卡完成，再重新评估可派发集合
                finished, _ = wait(futures, return_when=FIRST_COMPLETED)
                for fut in finished:
                    tid = futures.pop(fut)
                    res = fut.result()
                    results.append(res)
                    (failed if res.get("verdict") == "escalated" else done).add(tid)
        return results

    def run_card(self, card_path: Path) -> dict:
        """--card 模式：跳过架构师拆任务，直接执行一张手写/外来的任务卡。"""
        packet, card = load_card(card_path)
        print(f"[card] 载入任务卡: {card_path}")
        card.notes.append(f"由 --card 模式载入，来源: {card_path}")
        card.save(self.tasks_dir)
        self.cards[packet.task_id] = card
        print(f"\n--- 子任务 {packet.task_id}: {packet.goal[:60]}")
        return self._finish([self._execute_packet(packet, card)])

    def run_cards(self, cards_dir: Path, resume: bool = False) -> dict:
        """--cards 模式（PM 卡盒）：读入目录下全部任务卡，按依赖关系批量并行调度。
        resume=True 时（断点续跑）：done 卡跳过不重跑（依赖视为已满足），
        doing/rework 卡重置为 todo 续跑，escalated 卡保持人工持有不动。"""
        cards_dir = Path(cards_dir)
        files = sorted(cards_dir.glob("*.md"))
        if not files:
            raise RuntimeError(f"卡盒目录里没有 .md 任务卡: {cards_dir}")
        packets: dict[str, tuple[HandoffPacket, TaskCard]] = {}
        pre_done: set[str] = set()
        results: list[dict] = []
        for f in files:
            packet, card = load_card(f)
            if packet.task_id in packets:
                raise RuntimeError(f"任务卡 id 重复: {packet.task_id}（{f}）")
            if resume:
                if card.status == "done":
                    pre_done.add(packet.task_id)
                    results.append({"task_id": packet.task_id, "verdict": "skipped",
                                    "reason": "断点续跑：已完成，跳过不重跑"})
                    print(f"[resume] {packet.task_id}: 已完成，跳过")
                    self.cards[packet.task_id] = card
                    continue
                if card.status in ("doing", "rework"):
                    card.touch(status="todo", owner="architect")
                    card.notes.append("断点续跑：中断状态重置为 todo 续跑")
                    print(f"[resume] {packet.task_id}: {card.status} → 重置续跑")
            card.notes.append(f"由 --cards 模式载入，来源: {f}")
            card.save(self.tasks_dir)
            self.cards[packet.task_id] = card
            packets[packet.task_id] = (packet, card)
            print(f"[card] {packet.task_id}: {packet.goal[:60]}"
                  + (f"（依赖: {', '.join(packet.depends_on)}）" if packet.depends_on else ""))
        print(f"[pm] 卡盒共 {len(packets)} 张待执行（跳过 {len(pre_done)} 张已完成），开始调度")
        results.extend(self._schedule(packets, pre_done=pre_done))
        return self._finish(results)

    def _execute_packet(self, packet: HandoffPacket, card: TaskCard) -> dict:
        """单张卡的执行循环：工程师执行 → 验证器取证 → 架构师验收 → 通过/返工/升级。"""
        failures = 0
        while True:
            # 2. 工程师执行（卡片状态置 doing）
            card.touch(status="doing", owner="engineer")
            card.save(self.tasks_dir)
            self.events.emit("card_status", packet.task_id, status="doing", owner="engineer")
            eng = run_engineer(packet, self.workdir, self.engineer,
                               search_backend=card.search_backend,
                               system_prompt=role_prompt("engineer", "prompt", ENGINEER_SYS),
                               allowed_tools=(CONFIG.get("roles") or {})
                                             .get("engineer", {}).get("tools"),
                               events=self.events, card_id=packet.task_id)
            print(f"[engineer] {eng['status']}: {eng['summary'][:80]}")
            self.events.emit("engineer_status", packet.task_id, status=eng["status"],
                             summary=eng["summary"][:200])
            # 结构化回报写入卡片
            card.report = (f"状态: {eng['status']}\n\n{eng['summary']}\n\n"
                           f"工具调用: {json.dumps(eng.get('tool_calls', {}), ensure_ascii=False)}")
            card.touch(owner="architect")
            card.save(self.tasks_dir)
            # 3. 验证器跑真实检查（产出新信息——执行证据）
            ver = verify(packet, self.workdir)
            for ev in ver["evidence"]:   # 验证法庭：每条验收命令的真实结果
                self.events.emit("verify", packet.task_id, check=ev["check"][:120],
                                 passed=ev["passed"], output=ev["output"][:200])
            # 4. 架构师基于证据验收（审核者读独立证据，而非只听提议者自述）
            review_payload = {
                "packet": asdict(packet), "engineer_report": eng,
                "verification": ver}
            if eng["status"] != "finished":
                # 实验 015 教训：预算耗尽/隐式收尾 ≠ 任务失败——提示架构师只看证据
                review_payload["process_note"] = (
                    f"工程师未走 finish 流程（{eng['status']}）。"
                    f"其实际写过的文件: {eng.get('written_files', [])}。"
                    "请仅以验证器证据与落盘产物判定，不因流程缺失本身否决。")
            review = ask_json(self.architect, role_prompt("architect", "prompt_review",
                              ARCHITECT_REVIEW_SYS), json.dumps(
                review_payload, ensure_ascii=False))
            self.log_handoff(f"{packet.task_id}-review.json",
                             {"engineer": eng, "verification": ver, "review": review})
            self.events.emit("review", packet.task_id, verdict=review.get("verdict", "?"),
                             reason=review.get("reason", "")[:200])
            if review.get("verdict") == "pass" and ver["all_passed"]:
                print(f"[architect] ✓ 通过: {review.get('reason', '')[:80]}")
                card.touch(status="done")
                card.notes.append("验收通过: " + review.get("reason", ""))
                card.save(self.tasks_dir)
                self.events.emit("card_status", packet.task_id, status="done", owner="")
                return {"task_id": packet.task_id, "review": review}
            failures += 1
            print(f"[architect] ✗ 返工({failures}): {review.get('fix_instructions', '')[:80]}")
            if failures > CONFIG["escalation"]["max_verify_failures"]:
                # 升级策略：连续失败则记录并交还人工（人工干预，书 1.2.6.2）
                card.touch(status="escalated", owner="human")
                card.notes.append("连续返工超限，升级人工: " + review.get("fix_instructions", ""))
                card.save(self.tasks_dir)
                self.events.emit("card_status", packet.task_id, status="escalated", owner="human")
                return {"task_id": packet.task_id, "verdict": "escalated",
                        "reason": "连续返工超限，需人工介入", "last_review": review}
            # 返工：修复指令写入移交包 + 追加进卡片备注，预算收紧
            card.touch(status="rework")
            card.notes.append(f"返工({failures}): " + review.get("fix_instructions", ""))
            card.save(self.tasks_dir)
            self.events.emit("card_status", packet.task_id, status="rework", owner="architect")
            packet.confirmed_facts.append("上次返工原因: " + review.get("fix_instructions", ""))
            packet.remaining_budget = max(packet.remaining_budget // 2, 4)

    def _finish(self, results: list) -> dict:
        report = {"task": self.task, "results": results,
                  "cards": [str(self.tasks_dir / f"card-{c.task_id}.md") for c in self.cards.values()],
                  "cost": self.tracker.records, "run_dir": str(self.run_dir)}
        (self.run_dir / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(self.tracker.summary())
        print(f"\n[done] 报告: {self.run_dir / 'report.json'}")
        return report


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('用法: python orchestrator.py "你的任务描述"')
        print('      python orchestrator.py --plan-only "任务"   （只拆卡不执行，审卡后再放行）')
        print('      python orchestrator.py --card  <任务卡.md>')
        print('      python orchestrator.py --cards <卡盒目录>')
        print('      python orchestrator.py --resume <run目录> （断点续跑：done 跳过，中断卡重置续跑）')
        sys.exit(1)
    if sys.argv[1] == "--card":
        if len(sys.argv) < 3:
            print("缺少任务卡路径"); sys.exit(1)
        Orchestrator(f"--card {sys.argv[2]}").run_card(Path(sys.argv[2]))
    elif sys.argv[1] == "--cards":
        if len(sys.argv) < 3:
            print("缺少卡盒目录"); sys.exit(1)
        Orchestrator(f"--cards {sys.argv[2]}").run_cards(Path(sys.argv[2]))
    elif sys.argv[1] == "--resume":
        if len(sys.argv) < 3:
            print("缺少 run 目录路径"); sys.exit(1)
        rd = Path(sys.argv[2])
        if not (rd / "tasks").is_dir():
            print(f"不是有效 run 目录（缺 tasks/）: {rd}"); sys.exit(1)
        Orchestrator(f"--resume {rd}", run_dir=rd).run_cards(rd / "tasks", resume=True)
    elif sys.argv[1] == "--plan-only":
        if len(sys.argv) < 3:
            print("缺少任务描述"); sys.exit(1)
        Orchestrator(sys.argv[2]).run(plan_only=True)
    else:
        Orchestrator(sys.argv[1]).run()
