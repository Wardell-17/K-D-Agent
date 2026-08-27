---
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
