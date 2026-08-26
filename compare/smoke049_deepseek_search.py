# 实验 049 冒烟：_search_deepseek 直连官方端点 + usage 自记账
import importlib.util
import sys
from pathlib import Path

ORCH = Path(r"D:\agent-project\architect-engineer\orchestrator.py")
LOG = Path(r"D:\agent-project\compare\smoke049-cost.jsonl")
if LOG.exists():
    LOG.unlink()

spec = importlib.util.spec_from_file_location("orch", ORCH)
orch = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(ORCH.parent))
sys.modules["orch"] = orch   # dataclass 处理需要模块已注册
spec.loader.exec_module(orch)

# 挂临时 tracker，验证记账落盘
orch._ACTIVE_TRACKER = orch.CostTracker(LOG)

QUERY = "2026年7月中国官方制造业PMI数值是多少？数据发布机构和发布日期是什么？"

print("=== 1) 显式 backend=deepseek ===")
out = orch.web_search(QUERY, 5, "deepseek")
print((out or "None")[:1200])

print("\n=== 2) auto 链（tavily 无 key 时应降级到 deepseek）===")
import os
os.environ.pop("TAVILY_API_KEY", None)
out2 = orch.web_search(QUERY, 5, "auto")
print((out2 or "None")[:400])

print("\n=== 3) cost.jsonl 记账验证 ===")
if LOG.exists():
    for line in LOG.read_text(encoding="utf-8").splitlines():
        print(line)
else:
    print("!! cost.jsonl 未生成——记账钩子未生效")

print("\n=== 汇总 ===")
print(orch._ACTIVE_TRACKER.summary())
