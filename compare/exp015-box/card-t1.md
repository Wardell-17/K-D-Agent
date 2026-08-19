---
id: "t1"
title: "DSH 总体架构分层调研"
status: "todo"
owner: "architect"
created: "2026-08-19T15:37:39"
updated: "2026-08-19T16:00:00"
depends_on: []
---

# 任务卡 t1：DSH 总体架构分层调研

## 目标

通读 deepseek-harness 源码（位于 D:\agent-project\harness-src，pnpm monorepo）中负责总体架构的部分，产出中间成果文件 findings/arch-layers.md（相对路径，写在当前工作目录下）。内容必须覆盖：DSH 的总体架构分层——packages/ 下约 50 个 package 如何分层：apps/cli、apps/web 入口层，core/host/session/workflow 等核心层，llm/credentials/subagent 等能力层，util/fs/storage 等基础设施层——以实际读到的依赖关系为准（抽查各 package 的 package.json dependencies 与关键 import），禁止凭目录名臆测。

## 验收标准

- !python -c "import pathlib; p=pathlib.Path('findings/arch-layers.md'); assert p.exists() and p.stat().st_size>2000, 'file missing or too small'"
- !python -c "import pathlib; t=pathlib.Path('findings/arch-layers.md').read_text(encoding='utf-8'); [(_ for _ in ()).throw(AssertionError('missing: '+k)) for k in ['apps/cli','apps/web','core','llm','credentials','subagent','util','storage'] if k not in t]"
- 文中每个分层归属必须附证据（package.json 依赖或源码 import 引用），不得仅凭目录名推断

## 已确认事实与约束

- 运行环境是 Windows，验收与探索命令只能用 python 或 Windows 原生命令（dir/type），严禁 Unix 命令
- DSH 源码位于 D:\agent-project\harness-src（在工作目录之外，用 read_file 以绝对路径读取，这是只读的，允许；写入只能在当前工作目录内）
- 分层结论必须以实际读到的依赖关系为准，禁止凭目录名臆测
- 本任务只写 findings/arch-layers.md，禁止写其他成果文件；若发现 findings/ 下已有并行任务产出的其他文件，属正常，不要覆盖

## 产物引用

- D:\agent-project\harness-src\packages
- D:\agent-project\harness-src\apps

## 结构化回报

（待工程师完成后填写）

## 返工与备注

- 人工审批门修订：产物路径由 D:\agent-project\ 根目录改为工作目录内相对路径（工程师沙箱只允许写工作目录）
