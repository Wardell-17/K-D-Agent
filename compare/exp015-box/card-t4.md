---
id: "t4"
title: "集成卡：harness-vs-mvp 架构对比报告"
status: "done"
owner: "architect"
created: "2026-08-19T15:37:39"
updated: "2026-08-19T16:30:00"
depends_on: ["t1", "t2", "t2b", "t3"]
---

# 任务卡 t4：集成卡：harness-vs-mvp 架构对比报告

## 目标

基于四份中间成果撰写最终交付文件 harness-vs-mvp.md（相对路径，写在当前工作目录根部）。四份中间成果位于 D:\agent-project\architect-engineer\runs\20260819-154443\workspace\findings\ 下（用 read_file 以绝对路径读取，已授权只读）：

- arch-layers.md（DSH 总体架构分层）
- startup.md（DSH 完整启动链路）
- subsystems.md（DSH 四子系统深读：llm / credentials / subagent / preset）
- mvp.md（我方 orchestrator.py 分析）

报告章节结构（必须严格按此）：
1. **DSH 总体架构与启动链路**（基于 arch-layers + startup，可压缩复述，保留关键文件路径证据）
2. **四子系统对比**：llm / credentials / subagent / preset 各一小节，每节三段式——DSH 怎么实现（引 subsystems.md 的证据）vs 我们 MVP 怎么实现（引 mvp.md 的证据）vs 谁的设计更好及理由
3. **总结：DSH 哪些机制值得吸收进 MVP 路线图**（至少 4 条，每条说明吸收价值与改造成本）
开头加不超过 10 行的摘要。所有事实性结论必须能回溯到四份 findings 里的源码路径证据，禁止引入 findings 之外的新断言。

## 验收标准

- !python -c "import pathlib; p=pathlib.Path('harness-vs-mvp.md'); assert p.exists() and p.stat().st_size>5000, 'file missing or too small'"
- !python -c "import pathlib; t=pathlib.Path('harness-vs-mvp.md').read_text(encoding='utf-8'); [(_ for _ in ()).throw(AssertionError('missing: '+k)) for k in ['llm','credentials','subagent','preset','路线图','摘要'] if k not in t]"
- !python -c "import pathlib,re; t=pathlib.Path('harness-vs-mvp.md').read_text(encoding='utf-8'); paths=re.findall(r'[\w\-/\\\\.]+\\.(?:ts|js|py)', t); assert len(paths)>=10, 'too few source file references'"
- 第 2 章四个子系统小节齐全，每节含 DSH/MVP/评判 三段对照

## 已确认事实与约束

- 运行环境是 Windows，验收命令只能用 python
- 你是集成者：先用 read_file 以绝对路径读完四份 findings 再动笔；事实只能来自这四份文件
- 发现四份文件之间有矛盾时，在文中如实标注矛盾点，不得擅自二选一
- 本任务只写 harness-vs-mvp.md（当前工作目录根部），禁止写其他成果文件

## 产物引用

- D:\agent-project\architect-engineer\runs\20260819-154443\workspace\findings\arch-layers.md
- D:\agent-project\architect-engineer\runs\20260819-154443\workspace\findings\startup.md
- D:\agent-project\architect-engineer\runs\20260819-154443\workspace\findings\subsystems.md
- D:\agent-project\architect-engineer\runs\20260819-154443\workspace\findings\mvp.md

## 结构化回报

（待工程师完成后填写）

## 返工与备注

- 人工验收通过：三条验收命令手动执行全过，四子系统三段对照齐全

- 人工审批门重写：① 补入 t2b 依赖；② 交付物从「原文拼接」改为「真正的对比报告」；③ 产物路径改相对路径
- 人工恢复：t2/t2b 实际产物已落盘且经抽查合格（升级原因为预算耗尽的流程问题），本卡改为跨 run 绝对路径引用四份 findings 后单独放行
