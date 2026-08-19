---
id: "t2b"
title: "DSH 四大子系统源码级深读"
status: "done"
owner: "architect"
created: "2026-08-19T16:00:00"
updated: "2026-08-19T16:00:00"
depends_on: []
---

# 任务卡 t2b：DSH 四大子系统源码级深读

## 目标

深读 deepseek-harness 源码（D:\agent-project\harness-src\packages）中四个子系统，产出中间成果文件 findings/subsystems.md（相对路径）。这四个子系统是我们在使用中亲测踩过坑的，必须给出源码级结论：

1. **llm**：多模型 provider 如何抽象与路由？web 搜索后端如何接入（我们实测其检索流量走了 /anthropic/v1 端点 + deepseek-v4-flash，且 usage 未计入会话账单——请在源码中找到对应实现，解释记账缺口在哪）？
2. **credentials**：凭证服务的解析顺序是什么？我们实测"credentials 服务存在但无记录时直接抛 MISSING_CREDENTIAL，不回落环境变量"——请在源码中找到这段逻辑并引用。
3. **subagent**：子代理如何被创建与派工？它的工具集/权限与主代理有何差异（我们实测子代理工具权限被阉割、spawn 后不干活）？
4. **preset**：预设（.agent-presets / agent.cordis.yml）如何被加载、合并与校验？工具白名单如何生效？

每个子系统一节，结论必须附源码文件路径（+ 尽量给出函数/类名）。

## 验收标准

- !python -c "import pathlib; p=pathlib.Path('findings/subsystems.md'); assert p.exists() and p.stat().st_size>3000, 'file missing or too small'"
- !python -c "import pathlib; t=pathlib.Path('findings/subsystems.md').read_text(encoding='utf-8'); [(_ for _ in ()).throw(AssertionError('missing: '+k)) for k in ['llm','credentials','subagent','preset'] if k not in t]"
- !python -c "import pathlib,re; t=pathlib.Path('findings/subsystems.md').read_text(encoding='utf-8'); paths=re.findall(r'[\w\-/\\\\.]+\\.(?:ts|js|mjs|cjs)', t); assert len(paths)>=8, 'too few source file references'"
- 四个子系统每节至少引用 2 个真实源码文件路径

## 已确认事实与约束

- 运行环境是 Windows，探索命令只能用 python 或 Windows 原生命令，严禁 Unix 命令
- DSH 源码在 D:\agent-project\harness-src（read_file 绝对路径只读，已授权；写入只能在当前工作目录内）
- 所有结论必须基于真实读到的源码，读不懂的模块如实标注「未读懂」，禁止编造
- 本任务只写 findings/subsystems.md，禁止写其他成果文件

## 产物引用

- D:\agent-project\harness-src\packages\llm
- D:\agent-project\harness-src\packages\credentials
- D:\agent-project\harness-src\packages\subagent
- D:\agent-project\harness-src\packages\preset

## 结构化回报

（待工程师完成后填写）

## 返工与备注

- 人工恢复：产物已落盘且抽查合格（预算耗尽属流程问题），人工验收通过

- 人工审批门新增卡：架构师初版拆卡丢失了原任务第 2 点（四子系统深读），人工补卡
