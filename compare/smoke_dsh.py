# smoke_dsh.py —— DSH 升级过闸脚本（方案 1：自动回归闸门）
#
# 用途：每次 DSH 升级后运行一次，三盏灯全绿才放行日常使用。
#   灯1 preset 静态契约：preset 文件完好、persona 含关键纪律锚点
#   灯2 派发链路：keys 就位、kd_dispatch.ps1 在、orchestrator.py 可编译
#   灯3 端到端：跑一道已知答案的极小卡，断言 report.json + 双角色入账 + 产物正确
#
# 用法：  C:\Python314\python.exe compare\smoke_dsh.py
# 退出码：0 全绿 / 1 有红灯。红灯输出自带定位，按提示修。
#
# 如实标注：灯1 是静态检查——preset 在 DSH 界面里的真实加载无法从外部断言，
# 升级后请在 DSH 里肉眼确认一次 preset 出现在列表中（10 秒的事）。

import json
import subprocess
import sys
import time
import winreg
from pathlib import Path

ROOT = Path(r"D:\agent-project")
AE = ROOT / "architect-engineer"
PRESET = ROOT / "dsh-home" / ".agent-presets" / "kd-commander"
SMOKE = ROOT / "compare" / "smoke-dsh"

failures = []


def lamp(name, ok, detail=""):
    print(f"[{'绿灯' if ok else '红灯'}] {name}" + (f" —— {detail}" if detail else ""))
    if not ok:
        failures.append(name)


# ── 灯 1：preset 静态契约 ─────────────────────────────────────────────────
p_yml = PRESET / "preset.yml"
a_yml = PRESET / "agent.cordis.yml"
lamp("灯1a preset 文件存在", p_yml.exists() and a_yml.exists(),
     f"缺 {[str(p) for p in (p_yml, a_yml) if not p.exists()]}" if not (p_yml.exists() and a_yml.exists()) else "")

anchors = ["kd_dispatch", "审批", "orchestrator", "终审"]
text = a_yml.read_text(encoding="utf-8") if a_yml.exists() else ""
missing = [a for a in anchors if a not in text]
lamp("灯1b persona 纪律锚点", not missing, f"缺锚点 {missing}" if missing else f"锚点齐全 {anchors}")


# ── 灯 2：派发链路 ─────────────────────────────────────────────────────────
keys = {}
try:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
        for n in ("KIMI_API_KEY", "DEEPSEEK_API_KEY"):
            try:
                keys[n] = bool(winreg.QueryValueEx(k, n)[0])
            except OSError:
                keys[n] = False
except OSError:
    pass
lamp("灯2a API keys（注册表）", all(keys.values()),
     f"KIMI={'有' if keys.get('KIMI_API_KEY') else '缺'} DEEPSEEK={'有' if keys.get('DEEPSEEK_API_KEY') else '缺'}")

disp = AE / "kd_dispatch.ps1"
lamp("灯2b kd_dispatch.ps1", disp.exists())

r = subprocess.run([sys.executable, "-m", "py_compile", str(AE / "orchestrator.py")],
                   capture_output=True)
lamp("灯2c orchestrator 可编译", r.returncode == 0,
     r.stderr.decode("utf-8", "replace")[:200] if r.returncode else "")

# 契约锚点：orchestrator 的卡片/报告接口没漂移
src = (AE / "orchestrator.py").read_text(encoding="utf-8")
contract = ["--cards", "--resume", "report.json", "cost.jsonl", "budget", "depends_on"]
drift = [c for c in contract if c not in src]
lamp("灯2d 编排器接口契约", not drift, f"契约漂移 {drift}" if drift else f"锚定 {contract}")


# ── 灯 3：端到端单题 ───────────────────────────────────────────────────────
cards = SMOKE / "cards"
cards.mkdir(parents=True, exist_ok=True)
(cards / "card-smoke.md").write_text('''---
id: "smoke"
title: "DSH 过闸烟题"
status: "todo"
owner: "architect"
budget: 15
depends_on: []
---

## 目标
把字符串 OK 写入 `answer_smoke.txt`（单行，仅这两个字母）。

## 验收标准
- !python -c "import pathlib; t=pathlib.Path('answer_smoke.txt').read_text(encoding='utf-8').strip(); print('PASS' if t=='OK' else 'FAIL')"

## 产物引用
- （无）

## 约束
- Windows + python，写文件 UTF-8。这是过闸烟题，一轮即可完成。
''', encoding="utf-8")

print("\n[灯3] 启动端到端烟题（约 ¥0.01）……")
t0 = time.time()
before = {p for p in (AE / "runs").iterdir() if p.is_dir()}
proc = subprocess.run(
    [sys.executable, "orchestrator.py", "--cards", str(cards)],
    cwd=AE, capture_output=True, text=True, encoding="utf-8", errors="replace",
    env={**__import__("os").environ, "PYTHONUTF8": "1"}, timeout=280)
new_dirs = [p for p in (AE / "runs").iterdir()
            if p.is_dir() and p not in before and p.stat().st_mtime >= t0 - 5]
run_dir = new_dirs[0] if new_dirs else None
lamp("灯3a 编排器跑完", proc.returncode == 0 and run_dir is not None,
     f"exit={proc.returncode}" + ("" if run_dir else "，未找到新 run 目录"))

if run_dir:
    rep = run_dir / "report.json"
    cost = run_dir / "cost.jsonl"
    ans = run_dir / "workspace" / "answer_smoke.txt"
    rep_ok = rep.exists() and '"verdict": "pass"' in rep.read_text(encoding="utf-8")
    lamp("灯3b report.json verdict=pass", rep_ok)
    roles = set()
    if cost.exists():
        for line in cost.read_text(encoding="utf-8").splitlines():
            try:
                roles.add(json.loads(line)["role"])
            except json.JSONDecodeError:
                pass
    lamp("灯3c 双角色入账", {"engineer", "architect"} <= roles, f"角色={sorted(roles)}")
    lamp("灯3d 产物正确", ans.exists() and ans.read_text(encoding="utf-8").strip() == "OK")
    print(f"     耗时 {time.time()-t0:.0f}s ｜ run: {run_dir.name}")

print("\n===== 过闸结论 =====")
if failures:
    print(f"红灯 {len(failures)} 盏：{failures}")
    print("提示：灯1 红灯 → preset 文件被升级破坏；灯2 红灯 → 凭证/路径/接口漂移；灯3 红灯 → 端到端链路断了，看 run 目录 events.jsonl 定位")
    sys.exit(1)
print("三灯全绿，DSH 升级可放行。（记得在 DSH 界面肉眼确认 preset 仍在列表中）")
sys.exit(0)
