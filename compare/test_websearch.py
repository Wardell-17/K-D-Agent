import sys
sys.path.insert(0, r"D:\agent-project\architect-engineer")
from orchestrator import web_search

queries = [
    "GB 17761-2024 电动自行车安全技术规范 实施日期",
    "深圳 电动自行车 保有量 2025",
]
for q in queries:
    print("=" * 60)
    print(web_search(q, 5))
    print()
