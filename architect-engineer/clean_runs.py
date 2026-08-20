# clean_runs.py —— runs/ 目录分层清理（实验 018 运维工具）
# 策略（业内惯例映射：MLflow 元数据永留 + CI 最近 10 次完整保留 + 实验引用白名单）：
#   永久保留：report.json / cost.jsonl / tasks/（KB 级元数据，审计与学习资产）
#   瘦身删除：workspace/ 与 handoffs/（产物副本与过程记录，体积大头）
#   白名单：compare/实验记录-*.md 中引用过的 run 目录名，永不动
#   最近 KEEP_FULL 个 run：完整保留，不瘦身
# 用法：
#   python clean_runs.py           # dry-run 预览（默认，不删任何东西）
#   python clean_runs.py --apply   # 真正执行
import sys
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / "runs"
KEEP_FULL = 10
PROJECT = ROOT.parent  # agent-project/


def collect_whitelist() -> set[str]:
    """从实验记录中提取被引用的 run 目录名（如 20260819-154443）。"""
    wl = set()
    for f in (PROJECT / "compare").glob("实验记录-*.md"):
        wl.update(re.findall(r"20\d{6}-\d{6}", f.read_text(encoding="utf-8")))
    return wl


def dir_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def main() -> None:
    apply = "--apply" in sys.argv
    runs = sorted((d for d in RUNS.iterdir() if d.is_dir()),
                  key=lambda d: d.name, reverse=True)  # 时间戳命名，倒序=最新在前
    whitelist = collect_whitelist()
    freed = 0
    print(f"共 {len(runs)} 个 run | 完整保留最近 {KEEP_FULL} 个 | "
          f"白名单 {len(whitelist)} 个（实验记录引用）")
    print(f"模式: {'⚠ 实际删除' if apply else 'dry-run 预览（加 --apply 才真删）'}\n")
    for i, d in enumerate(runs):
        recent = i < KEEP_FULL
        pinned = d.name in whitelist
        if recent or pinned:
            tag = "保留(最近)" if recent else "保留(白名单)"
            print(f"  [=] {d.name}  {tag}")
            continue
        slimmed = []
        for sub in ("workspace", "handoffs"):
            p = d / sub
            if p.exists():
                sz = dir_size(p)
                freed += sz
                slimmed.append(f"{sub}/({sz // 1024}KB)")
                if apply:
                    shutil.rmtree(p)
        # 连元数据都没有的作废 run（如中断残留空壳）→ 整目录删
        if not (d / "report.json").exists() and not any((d / "tasks").glob("*.md")) \
                if (d / "tasks").exists() else not (d / "report.json").exists():
            slimmed.append("整个目录(无元数据)")
            if apply:
                shutil.rmtree(d, ignore_errors=True)
        print(f"  [-] {d.name}  瘦身: {', '.join(slimmed) or '已是瘦状态'}")
    print(f"\n{'已释放' if apply else '预计可释放'}: {freed / 1024 / 1024:.1f} MB")
    print("保留内容：report.json / cost.jsonl / tasks/*.md（审计与复盘资产）")


if __name__ == "__main__":
    main()
