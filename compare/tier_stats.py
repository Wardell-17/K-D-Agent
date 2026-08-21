# -*- coding: utf-8 -*-
"""分层基线统计：按 S/M/L 切开 75+ runs 的成本/返工率/预算命中率
用途：验证"历史 run 数据反哺拆卡决策"是否有真规律（实验 024 候选）
口径：
  - tier：优先读 handoffs/plan.json 的声明式 tier（021 起）；
          历史单兜底启发式 = max(budget)>=25 且卡数>=2 -> L；max(budget)>=25 或卡数>=3 -> M；否则 S
  - 返工：handoffs/ 下某卡的 review 文件数 - 1（首次验收不记返工）；escalated 卡记人工介入
  - 预算命中率：工程师 LLM 调用轮数 / 卡片 budget（无 budget 卡用全局默认 12）
"""
import json, re, sys
from pathlib import Path
from collections import defaultdict

RUNS = Path(r"D:\agent-project\architect-engineer\runs")
DEFAULT_BUDGET = 12

def parse_card(p: Path):
    txt = p.read_text(encoding="utf-8", errors="replace")
    m = re.match(r"^---\s*\n(.*?)\n---", txt, re.S)
    meta = {}
    if m:
        for line in m.group(1).splitlines():
            kv = line.split(":", 1)
            if len(kv) == 2:
                meta[kv[0].strip()] = kv[1].strip().strip('"')
    return meta

rows = []
skipped = []
for run in sorted(RUNS.iterdir()):
    if not run.is_dir():
        continue
    tasks = run / "tasks"
    cost_f = run / "cost.jsonl"
    if not tasks.exists() or not cost_f.exists():
        skipped.append(run.name)
        continue
    cards = {p.stem: parse_card(p) for p in tasks.glob("*.md")}
    if not cards:
        skipped.append(run.name)
        continue
    # 成本与调用轮数
    cost = {"architect": 0.0, "engineer": 0.0}
    eng_calls = 0
    arch_calls = 0
    for line in cost_f.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        role = r.get("role", "")
        if role in cost:
            cost[role] += r.get("cost_cny", 0.0)
            if role == "engineer":
                eng_calls += 1
            else:
                arch_calls += 1
    # tier
    tier = None
    plan = run / "handoffs" / "plan.json"
    if plan.exists():
        try:
            tier = json.loads(plan.read_text(encoding="utf-8", errors="replace")).get("tier")
        except Exception:
            pass
    budgets = []
    for c in cards.values():
        try:
            budgets.append(int(c.get("budget", DEFAULT_BUDGET)))
        except ValueError:
            budgets.append(DEFAULT_BUDGET)
    if not tier:
        mb, n = max(budgets), len(cards)
        tier = "L" if (mb >= 25 and n >= 2) else ("M" if (mb >= 25 or n >= 3) else "S")
    # 返工与升级：验收轮数 ≈ 架构师调用 - 1（规划）- 1（最终总结若有则多算，偏保守）；
    # 返工轮 = 验收轮 - 卡数（每卡至少一次验收，多出来的即返工；下限 0）
    escalated = sum(1 for c in cards.values() if c.get("status") == "escalated")
    done = sum(1 for c in cards.values() if c.get("status") == "done")
    review_rounds = max(0, arch_calls - 1)
    rework = max(0, review_rounds - len(cards))
    budget_total = sum(budgets)
    rows.append({
        "run": run.name, "tier": tier, "cards": len(cards),
        "done": done, "escalated": escalated, "rework": rework,
        "cost": cost["architect"] + cost["engineer"],
        "eng_calls": eng_calls, "budget": budget_total,
        "hit": eng_calls / budget_total if budget_total else 0.0,
    })

agg = defaultdict(list)
for r in rows:
    agg[r["tier"]].append(r)

print(f"总 runs: {len(rows)}（跳过无账本/无卡 {len(skipped)}）\n")
print(f"{'级别':<4}{'单数':>4}{'交付率':>8}{'返工/单':>8}{'升级/单':>8}{'均成本':>9}{'预算命中率':>10}")
for t in ("S", "M", "L"):
    g = agg.get(t, [])
    if not g:
        continue
    n = len(g)
    delivery = sum(1 for r in g if r["done"] == r["cards"] and r["escalated"] == 0) / n
    print(f"{t:<4}{n:>4}{delivery:>8.0%}{sum(r['rework'] for r in g)/n:>8.2f}"
          f"{sum(r['escalated'] for r in g)/n:>8.2f}{sum(r['cost'] for r in g)/n:>9.3f}"
          f"{sum(r['hit'] for r in g)/n:>10.0%}")
print()
# 预算命中率分桶：看超支集中在哪
over = [r for g in agg.values() for r in g if r["hit"] > 1.0]
print(f"超预算单数: {len(over)} / {len(rows)}")
for r in sorted(over, key=lambda x: -x["hit"])[:8]:
    print(f"  {r['run']} tier={r['tier']} 命中={r['hit']:.0%} 卡={r['cards']} 返工={r['rework']} ¥{r['cost']:.3f}")
# 成本方差提示
import statistics
for t in ("S", "M", "L"):
    g = [r["cost"] for r in agg.get(t, [])]
    if len(g) >= 2:
        print(f"{t} 级成本: mean=¥{statistics.mean(g):.3f} stdev=¥{statistics.stdev(g):.3f} "
              f"min=¥{min(g):.3f} max=¥{max(g):.3f}")
