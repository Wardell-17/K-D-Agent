---
id: "demo1"
title: "手写卡演示：生成今日日期文件"
status: "todo"
owner: "human"
created: "2026-08-17T15:30:00"
updated: "2026-08-17T15:30:00"
---

# 任务卡 demo1：手写卡演示

## 目标

编写 Python 脚本 today.py，运行后把当前日期（YYYY-MM-DD 格式）写入 today.txt

## 验收标准

- !python today.py
- !python -c "import re; print(bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}', open('today.txt', encoding='utf-8').read().strip())))" 输出 True

## 已确认事实与约束

- 运行环境是 Windows，用 python 执行
- 写入文件必须指定 encoding='utf-8'
- today.txt 内容只允许一行日期，不要多余文字

## 产物引用

- （无）

## 结构化回报

（待工程师完成后填写）

## 返工与备注

- （无）
