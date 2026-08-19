---
id: "t2"
title: "DSH 启动链路调研"
status: "done"
owner: "architect"
created: "2026-08-19T15:37:39"
updated: "2026-08-19T16:00:00"
depends_on: []
---

# 任务卡 t2：DSH 启动链路调研

## 目标

通读 deepseek-harness 源码（D:\agent-project\harness-src）中负责启动链路的部分，产出中间成果文件 findings/startup.md（相对路径）。内容必须覆盖：完整启动链路——从 apps/cli 的入口（package.json 的 bin/main 字段及对应源码文件）开始，沿实际调用链逐层追踪（命令解析、配置加载、session/host 初始化、进入 agent 主循环），直到主循环/服务监听为止；每一跳必须给出文件路径与函数/类名作为证据。

## 验收标准

- !python -c "import pathlib; p=pathlib.Path('findings/startup.md'); assert p.exists() and p.stat().st_size>2000, 'file missing or too small'"
- !python -c "import pathlib; t=pathlib.Path('findings/startup.md').read_text(encoding='utf-8'); [(_ for _ in ()).throw(AssertionError('missing: '+k)) for k in ['apps/cli','package.json','入口'] if k not in t]"
- !python -c "import pathlib,re; t=pathlib.Path('findings/startup.md').read_text(encoding='utf-8'); paths=re.findall(r'[\w\-/\\\\.]+\\.(?:ts|js|mjs|cjs|json)', t); assert len(paths)>=5, 'too few file references'"
- 启动链路每一步必须标注真实存在的文件路径

## 已确认事实与约束

- 运行环境是 Windows，探索命令只能用 python 或 Windows 原生命令（dir/type），严禁 Unix 命令
- DSH 源码在 D:\agent-project\harness-src（工作目录之外，read_file 用绝对路径只读访问，已获授权；写入只能在当前工作目录内）
- 追踪必须基于真实源码阅读并给出 文件路径+符号名 证据，禁止臆测
- 本任务只写 findings/startup.md，禁止写其他成果文件

## 产物引用

- D:\agent-project\harness-src\apps\cli

## 结构化回报

（待工程师完成后填写）

## 返工与备注

- 人工恢复：产物已落盘且抽查合格（预算耗尽属流程问题），人工验收通过

- 人工审批门修订：产物路径改为工作目录内相对路径（工程师沙箱只允许写工作目录）
