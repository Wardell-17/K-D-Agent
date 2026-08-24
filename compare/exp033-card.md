---
id: "t1"
title: "实验033：工程师视觉自测首航"
status: "todo"
owner: "architect"
budget: 15
require_visual: true
depends_on: []
---

## 目标

用 matplotlib 生成一张横向条形图 `sales.png`：
- 标题："月度销量"（注意中文渲染，不许出现方框乱码）
- 四个类别：一月=120、二月=95、三月=140、四月=110（横向条形，值标在条末端）
- 条形颜色：钢蓝色（steelblue）
- 尺寸 8x4.5 英寸，dpi=100
- 另交付 `gen_sales.py`（运行 `python gen_sales.py` 可复现该图）

交付前纪律：用 read_image 亲眼核验成品图再交（标题/数值/颜色/方向四项逐一核对）。

## 验收标准

- !python gen_sales.py
- !python -c "import os; assert os.path.exists('sales.png') and os.path.getsize('sales.png')>10000"
- 架构师审查：读图核验标题无乱码、四类别数值 120/95/140/110、钢蓝色、横向条形。

## 产物引用

- （无）
