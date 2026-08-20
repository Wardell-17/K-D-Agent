---
id: "smoke020"
title: "冒烟：提示词配置化后链路正常"
status: "todo"
owner: "human"
created: "2026-08-20T11:10:00"
updated: "2026-08-20T11:10:00"
depends_on: []
---

# 任务卡 smoke020

## 目标

在当前工作目录写入 hello.txt，内容为 hello。

## 验收标准

- !python -c "import pathlib; assert pathlib.Path('hello.txt').read_text(encoding='utf-8').strip()=='hello'; print('OK')"
