# -*- coding: utf-8 -*-
"""K-D Agent 指挥中心（实验 021）· Streamlit 单页看板
五区布局：大盘指标 → 发卡台（含审批门） → 任务看板+DAG → 执行心跳/验证法庭 → 档案馆/陈列室
原则：纯读盘渲染 + subprocess 派发，不侵入编排器内部状态。
启动：C:\\Python314\\python.exe -m streamlit run D:\\agent-project\\dashboard\\app.py
"""
import os
import subprocess
import sys
import time
import winreg
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reader  # noqa: E402

AE_DIR = reader.AE_DIR
PYTHON = sys.executable

st.set_page_config(page_title="K-D Agent 指挥中心", layout="wide", page_icon="🎛️")

# 状态语义色：绿 done/OK、蓝 doing、橙 rework、红 escalated/FAIL、灰 todo
STATUS_STYLE = {
    "done":      ("✅", "#1a7f37", "已完成"),
    "doing":     ("🔵", "#0969da", "执行中"),
    "rework":    ("🟠", "#bf6000", "返工中"),
    "escalated": ("🔴", "#cf222e", "人工介入"),
    "todo":      ("⚪", "#6e7781", "待办"),
}


def user_env() -> dict:
    """从 Windows 用户注册表读 API keys（setx 写入处），注入子进程。"""
    env = dict(os.environ)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            for name in ("KIMI_API_KEY", "DEEPSEEK_API_KEY", "TAVILY_API_KEY"):
                try:
                    env[name] = winreg.QueryValueEx(k, name)[0]
                except FileNotFoundError:
                    pass
    except OSError:
        pass
    return env


def launch_orchestrator(args: list[str]):
    """后台派发编排器进程（有限任务，跑完自退）。"""
    subprocess.Popen(
        [PYTHON, "orchestrator.py", *args],
        cwd=AE_DIR, env=user_env(),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)


# ---------------------------------------------------------------- 数据装载
runs = reader.list_runs()
run_names = [r.name for r in runs]
sel = st.session_state.get("run_sel", 0)
run_dir = runs[min(sel, len(runs) - 1)] if runs else None
cards = reader.load_cards(run_dir) if run_dir else []
cost = reader.load_cost(run_dir) if run_dir else {"total": 0.0, "by_role": {}}
events = reader.load_events(run_dir) if run_dir else []

st.title("🎛️ K-D Agent 指挥中心")
st.caption(f"Kimi K3 架构师 × DeepSeek V4 Flash 工程师 · 当前 run: `{run_dir.name if run_dir else '无'}`")

# ================= 一区：大盘指标 =================
done_n = sum(1 for c in cards if c["status"] == "done")
total_n = len(cards)
c1, c2, c3, c4 = st.columns([2, 1, 1, 2])
c1.metric("任务进度", f"{done_n}/{total_n} 卡")
c1.progress(done_n / total_n if total_n else 0.0)
c2.metric("总成本", f"¥{cost['total']:.4f}")
c3.metric("LLM 调用", f"{sum(v['calls'] for v in cost['by_role'].values())} 次")
with c4:
    if cost["by_role"]:
        fig = go.Figure(go.Pie(
            labels=[f"{r}（{v['model']}）" for r, v in cost["by_role"].items()],
            values=[v["cost"] for r, v in cost["by_role"].items()],
            hole=.55, textinfo="percent"))
        fig.update_layout(height=170, margin=dict(t=10, b=10, l=10, r=10),
                          showlegend=True, title=dict(text="双模型成本占比", font=dict(size=13)))
        st.plotly_chart(fig, width="stretch", key="cost_pie")

st.divider()

# ================= 二区：发卡台 =================
st.subheader("📮 发卡台")
task_text = st.text_area("任务描述（宏观意图即可，架构师负责拆卡）", height=90,
                         placeholder="例：写一个脚本统计……要求能跑通")
b1, b2 = st.columns(2)
if b1.button("🚀 直接执行", width="stretch", disabled=not task_text.strip()):
    launch_orchestrator([task_text.strip()])
    st.success("已派发：架构师拆卡后立即执行")
    time.sleep(1)
    st.rerun()
if b2.button("🚪 审批门模式（先拆卡，人审后放行）", width="stretch",
             disabled=not task_text.strip()):
    launch_orchestrator(["--plan-only", task_text.strip()])
    st.info("已派发 plan-only：卡片生成后在本页审阅/改预算，再点放行")
    time.sleep(2)
    st.rerun()

# 待审批卡盒：全部卡 todo 且无 report.json 的最新 run
pending_run = None
for r in runs:
    cs = reader.load_cards(r)
    if cs and all(c["status"] == "todo" for c in cs) and not (r / "report.json").exists():
        pending_run = (r, cs)
        break
if pending_run:
    pr, pcs = pending_run
    st.warning(f"📋 待审批卡盒：`{pr.name}` —— {len(pcs)} 张卡，审阅后可改预算/检索后端再放行")
    for c in pcs:
        with st.expander(f"卡 {c['id']}：{c['title']}", expanded=False):
            st.markdown(f"**目标**：{c['goal']}")
            nb = st.number_input("轮数预算（0=默认档）", 0, 40, int(c["budget"]),
                                 key=f"budget_{pr.name}_{c['id']}")
            sb = st.selectbox("检索后端", ["", "auto", "tavily", "ddg", "deepseek"],
                              index=["", "auto", "tavily", "ddg", "deepseek"].index(c["search_backend"] or ""),
                              key=f"sb_{pr.name}_{c['id']}")
            if st.button("保存修改", key=f"save_{pr.name}_{c['id']}"):
                from orchestrator import load_card
                tasks_dir = pr / "tasks"
                _, card_obj = load_card(tasks_dir / f"card-{c['id']}.md")
                card_obj.budget = nb
                card_obj.search_backend = sb
                card_obj.save(tasks_dir)
                st.success(f"卡 {c['id']} 已更新")
                time.sleep(0.5)
                st.rerun()
    if st.button("✅ 审毕放行（--cards 执行整个卡盒）", type="primary"):
        launch_orchestrator(["--cards", str(pr / "tasks")])
        st.success("已放行，卡盒进入并行调度")
        time.sleep(1)
        st.rerun()

st.divider()

# ================= 三区：任务看板 + DAG =================
st.subheader("🗂️ 任务看板")
cols = st.columns(4)
lanes = [("todo", "⚪ 待办"), ("doing", "🔵 执行中"),
         ("rework", "🟠 返工/介入"), ("done", "✅ 已完成")]
for col, (lane, label) in zip(cols, lanes):
    with col:
        st.markdown(f"**{label}**")
        for c in cards:
            in_lane = (c["status"] == lane) or (
                lane == "rework" and c["status"] == "escalated")
            if not in_lane:
                continue
            icon, color, _ = STATUS_STYLE[c["status"]]
            deps = f" ⛓️ ← {', '.join(c['depends_on'])}" if c["depends_on"] else ""
            st.markdown(
                f"<div style='border-left:4px solid {color};padding:6px 10px;"
                f"margin-bottom:8px;background:#f6f8fa;border-radius:4px'>"
                f"<b>{icon} {c['id']}</b>{deps}<br>"
                f"<span style='font-size:13px'>{c['title']}</span><br>"
                f"<span style='font-size:12px;color:#57606a'>预算 {c['budget']} 轮"
                f" · owner: {c['owner']}</span></div>",
                unsafe_allow_html=True)

if cards:
    with st.expander("🕸️ 依赖关系图（DAG）", expanded=any(c["depends_on"] for c in cards)):
        lines = ["digraph G {rankdir=LR; node [shape=box, style=filled, fontsize=11];"]
        for c in cards:
            _, color, _ = STATUS_STYLE[c["status"]]
            lines.append(f'"{c["id"]}" [fillcolor="{color}22", color="{color}"];')
            for d in c["depends_on"]:
                lines.append(f'"{d}" -> "{c["id"]}";')
        lines.append("}")
        st.graphviz_chart("\n".join(lines))

st.divider()

# ================= 四区：执行心跳 / 验证法庭 =================
st.subheader("💓 执行心跳 & ⚖️ 验证法庭")
h1, h2 = st.columns(2)
tool_events = [e for e in events if e.get("type") in ("tool", "engineer_status", "dispatch", "review")]
verify_events = [e for e in events if e.get("type") == "verify"]
with h1:
    st.markdown("**执行心跳**（工具调用 / 状态流转）")
    with st.container(height=320):
        for e in tool_events[-60:]:
            t = e.get("type")
            if t == "tool":
                st.text(f"{e['ts']} [{e['card']}] 🔧 {e.get('tool')}({e.get('args', '')})")
            elif t == "engineer_status":
                st.text(f"{e['ts']} [{e['card']}] 🧑‍🔧 {e.get('status')}: {e.get('summary', '')[:60]}")
            elif t == "dispatch":
                st.text(f"{e['ts']} [{e['card']}] 📤 派发（依赖: {e.get('depends_on')}）")
            elif t == "review":
                mark = "✓" if e.get("verdict") == "pass" else "✗"
                st.text(f"{e['ts']} [{e['card']}] 🏛️ {mark} {e.get('reason', '')[:60]}")
with h2:
    st.markdown("**验证法庭**（验收命令的真实执行结果）")
    with st.container(height=320):
        if not verify_events:
            st.caption("暂无验收记录")
        for e in verify_events[-40:]:
            block = st.success if e.get("passed") else st.error
            block(f"{e['ts']} [{e['card']}] `!{e.get('check', '')}`\n\n"
                  f"{e.get('output', '')[:180]}")

st.divider()

# ================= 五区：档案馆 / 陈列室 =================
st.subheader("🗄️ 档案馆 & 🧪 产物陈列室")
a1, a2 = st.columns([1, 2])
with a1:
    if runs:
        idx = st.selectbox("选择 run", range(len(runs)),
                           format_func=lambda i: runs[i].name, index=min(sel, len(runs) - 1))
        if idx != sel:
            st.session_state["run_sel"] = idx
            st.rerun()
    files = reader.workspace_files(run_dir) if run_dir else []
    file_rel = None
    if files:
        ws = run_dir / "workspace"
        rels = [str(f.relative_to(ws)) for f in files]
        file_rel = st.radio("产物文件", rels, key="artifact_sel")
with a2:
    if run_dir and file_rel:
        st.markdown(f"**{file_rel}**")
        suffix = Path(file_rel).suffix.lstrip(".") or "text"
        st.code(reader.read_artifact(run_dir, file_rel), language=suffix, line_numbers=True)
    elif run_dir:
        st.caption("产物区暂无文件")

# 自动刷新（2s 轮询磁盘事实）
if st.toggle("🔄 自动刷新（2s）", value=True):
    time.sleep(2)
    st.rerun()
