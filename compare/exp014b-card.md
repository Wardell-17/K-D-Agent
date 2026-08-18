---
id: "exp014b"
title: "事实清单：三条电动车领域事实"
status: "todo"
owner: "human"
created: "2026-08-18T11:55:00"
updated: "2026-08-18T18:00:00"
depends_on: []
search_backend: "ddg"
---

# 任务卡 exp014b

## 目标

创建 facts.md，内容为三条事实，每条一行、格式「事实内容 | 数据来源」：
1) GB 17761-2024《电动自行车安全技术规范》的实施日期；
2) 2025 年中国电动自行车社会保有量（工信部口径）；
3) 深圳市电动自行车上牌保有量（最新公开口径）。
每条必须给出具体数字/日期和来源名称。

## 验收标准

- !python -c "t=open('facts.md',encoding='utf-8').read(); lines=[l for l in t.splitlines() if l.strip()]; assert len(lines)==3 and all('|' in l for l in lines); print('OK')"
- !python -c "t=open('facts.md',encoding='utf-8').read(); assert '17761' in t and ('保有量' in t) and ('深圳' in t); print('OK')"

## 已确认事实与约束

- 运行环境 Windows，文件编码 UTF-8
- 如果你有 web_search 工具：必须用它核实每条事实，来源写真实检索到的名称；若无此工具则凭已有知识填写并标注
- facts.md 共三行，不要标题、编号或多余空行

## 产物引用

- （无）

## 结构化回报

（待工程师完成后填写）

## 返工与备注

- （无）
