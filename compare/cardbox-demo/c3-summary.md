---
id: "c3"
title: "汇总两个结果"
status: "todo"
owner: "human"
created: "2026-08-17T15:55:00"
updated: "2026-08-17T15:55:00"
depends_on: ["c1", "c2"]
---

# 任务卡 c3

## 目标

编写 summary.py，读取 fib.txt 和 primes.txt，把两个数合并成一行（格式 "fib=<值> primes=<值>"）写入 summary.txt

## 验收标准

- !python summary.py
- !python -c "print(open('summary.txt', encoding='utf-8').read().strip() == 'fib=6765 primes=15')" 输出 True

## 已确认事实与约束

- 运行环境是 Windows，用 python 执行
- fib.txt 与 primes.txt 由前置任务 c1、c2 生成，本任务只读不写它们
- 写文件指定 encoding='utf-8'

## 产物引用

- fib.txt
- primes.txt

## 结构化回报

（待工程师完成后填写）

## 返工与备注

- （无）
