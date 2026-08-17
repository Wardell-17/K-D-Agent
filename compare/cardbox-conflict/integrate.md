---
id: "integrate"
title: "集成：组装 app.txt"
status: "todo"
owner: "human"
created: "2026-08-17T16:20:00"
updated: "2026-08-17T16:20:00"
depends_on: ["header", "footer"]
---

# 任务卡 integrate

## 目标

编写 assemble.py，读取 header.txt 和 footer.txt，把两行内容按顺序合并写入 app.txt（header 在前，footer 在后，各占一行）

## 验收标准

- !python assemble.py
- !python -c "print(open('app.txt', encoding='utf-8').read().splitlines() == ['<header>KD-Agent</header>', '<footer>MIT License</footer>'])" 输出 True

## 已确认事实与约束

- 运行环境是 Windows，用 python 执行，写文件指定 encoding='utf-8'
- header.txt 与 footer.txt 由前置卡 header、footer 生成，本卡只读它们，只写 app.txt
- 本卡是集成卡：共享文件 app.txt 的写入只能发生在这里

## 产物引用

- header.txt
- footer.txt

## 结构化回报

（待工程师完成后填写）

## 返工与备注

- （无）
