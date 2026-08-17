---
id: "footer"
title: "生成页面底部组件"
status: "todo"
owner: "human"
created: "2026-08-17T16:20:00"
updated: "2026-08-17T16:20:00"
depends_on: []
---

# 任务卡 footer

## 目标

编写 gen_footer.py，运行后把页面底部标记 `<footer>MIT License</footer>` 写入 footer.txt（只写这一个文件）

## 验收标准

- !python gen_footer.py
- !python -c "print(open('footer.txt', encoding='utf-8').read().strip() == '<footer>MIT License</footer>')" 输出 True

## 已确认事实与约束

- 运行环境是 Windows，用 python 执行，写文件指定 encoding='utf-8'
- 文件隔离纪律：本卡只许写 gen_footer.py 和 footer.txt，app.txt 由集成卡负责，严禁代写

## 产物引用

- （无）

## 结构化回报

（待工程师完成后填写）

## 返工与备注

- （无）
