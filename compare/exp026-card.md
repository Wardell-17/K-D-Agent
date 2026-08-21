---
id: "t1"
title: "返工纪律对照实验v3：水果清单脚本"
status: "todo"
owner: "human"
created: "2026-08-21T17:20:00"
updated: "2026-08-21T17:20:00"
depends_on: []
budget: 4
---

# 任务卡 t1：返工纪律对照实验 v3

## 目标

在当前目录创建 hello3.py，运行时逐行打印 apple、banana、cherry 三个单词，
并用 run_command 实际运行确认输出正确。

## 验收标准

- !python hello3.py
- !python -c "c=open('verdict.txt',encoding='utf-8').read().strip(); assert c=='PASS-026-V3', c"

## 已确认事实与约束

- 运行环境 Windows cmd.exe，无 Unix 命令
- 产物直接写当前目录，不要建子目录

## 产物引用

- （无）
