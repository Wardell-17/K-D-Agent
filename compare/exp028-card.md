---
id: "t1"
title: "视觉断言实测：生成指定规格的柱状图"
status: "todo"
owner: "human"
created: "2026-08-24T11:15:00"
updated: "2026-08-24T11:15:00"
depends_on: []
budget: 15
---

# 任务卡 t1：视觉断言实测

## 目标

在当前目录创建 gen_chart.py，用 matplotlib 生成柱状图并保存为 chart.png，规格：
1) 标题为 "KD-028 视觉验收"；2) 三根柱子，类别为 A/B/C，数值为 3/7/5；
3) 柱子颜色为红色（red）；4) 图片尺寸 6x4 英寸，DPI 100。
运行脚本确认 chart.png 生成。

## 验收标准

- !python gen_chart.py
- !python -c "import os; assert os.path.isfile('chart.png') and os.path.getsize('chart.png')>10000"
- 图片内容判据：标题文字正确、三根柱子、红色、数值标签或高度符合 3/7/5

## 已确认事实与约束

- 运行环境 Windows；当前 PATH 的 python 自带 matplotlib；中文标题若乱码用英文替代并注明
- 产物写当前目录

## 产物引用

- （无）
