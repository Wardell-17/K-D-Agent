# -*- coding: utf-8 -*-
"""一次性修复：存量任务卡 frontmatter 中未转义的反斜杠（YAML 双引号标量炸 ScannerError）"""
import re, pathlib, yaml

def fix(p: pathlib.Path) -> bool:
    t = p.read_text(encoding="utf-8")
    m = re.match(r"^(---\n)(.*?)(\n---)", t, re.S)
    if not m:
        return False
    fm = m.group(2)
    # 单反斜杠（前面不是反斜杠、后面也不是）→ 双反斜杠
    fixed = re.sub(r'\\(?![\\"])|(?<!\\)\\(?=")', '\\\\\\\\', fm)
    if fixed != fm:
        p.write_text(t[:m.start(2)] + fixed + t[m.end(2):], encoding="utf-8")
        return True
    return False

n = 0
for run in ("20260821-162250", "20260821-162427"):
    for c in pathlib.Path(rf"D:\agent-project\architect-engineer\runs\{run}\tasks").glob("*.md"):
        if fix(c):
            n += 1
            print("fixed:", run, c.name)
print("共修复", n, "张")

for run in ("20260821-162250", "20260821-162427"):
    for c in pathlib.Path(rf"D:\agent-project\architect-engineer\runs\{run}\tasks").glob("*.md"):
        fm = re.match(r"^---\n(.*?)\n---", c.read_text(encoding="utf-8"), re.S).group(1)
        yaml.safe_load(fm)
print("两盒卡 YAML 解析全部通过 OK")
