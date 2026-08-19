---
id: "recon_bottle"
title: "逆向调研：bottle.py 单文件库（翻页能力实测）"
status: "todo"
owner: "architect"
created: "2026-08-19T17:40:00"
updated: "2026-08-19T17:40:00"
depends_on: []
budget: 15
---

# 任务卡 recon_bottle：逆向调研 bottle.py 单文件库

## 目标

深读单文件 Web 框架 bottle.py（位于 D:\agent-project\target-repos\bottle\bottle.py，共 175882 字符 / 4584 行——注意：这是超大单文件，单次读取只能看到前 20000 字符），逆向梳理其整体架构并输出 bottle_architecture.md（相对路径，写在当前工作目录根部）。

文档必须覆盖四个部分：
1. 核心类清单与职责（应用类、请求/响应封装、路由系统）；
2. 路由匹配机制：URL 规则如何被编译、请求到来后如何找到处理函数；
3. 请求生命周期：从 WSGI 入口到调用用户处理函数再到响应返回的完整链路；
4. 服务器适配层：内置了哪些服务器后端适配器（逐个列出类名），run() 如何选择与启动它们。

每个结论必须附行号或符号名（类/方法名）；文件后段的内容必须基于真实阅读，禁止凭前半截臆测。

## 验收标准

- !python -c "import pathlib; p=pathlib.Path('bottle_architecture.md'); assert p.exists() and p.stat().st_size>2500, 'file missing or too small'"
- !python -c "import pathlib; t=pathlib.Path('bottle_architecture.md').read_text(encoding='utf-8'); [(_ for _ in ()).throw(AssertionError('missing: '+k)) for k in ['Router','路由','wsgi'] if k not in t]"
- !python -c "import pathlib; t=pathlib.Path('bottle_architecture.md').read_text(encoding='utf-8'); [(_ for _ in ()).throw(AssertionError('missing deep symbol: '+k)) for k in ['FileUpload','WSGIRefServer','GeventServer'] if k not in t]"
- 架构师审查：FileUpload / WSGIRefServer / GeventServer 均位于文件 10 万字符之后——若文档对这三处的描述具体准确（不是一句话带过），证明工程师真的翻页读到了文件后段；描述空洞或张冠李戴则返工

## 已确认事实与约束

- 运行环境是 Windows，探索命令只能用 python 或 Windows 原生命令，严禁 Unix 命令
- 目标文件在工作目录之外，用 read_file 以绝对路径只读访问（已授权）；写入只能在当前工作目录内
- 你有 15 轮预算。文件 17.6 万字符 = 约 9 页，请规划：先读开头摸清类清单，再有选择地翻页到关键符号所在位置，不要顺序翻完每一页
- 可以用 run_command 执行 python 做符号定位（如查找某类名在文件中的字符位置），把预算花在刀刃上
- 本任务只写 bottle_architecture.md，禁止写其他成果文件

## 产物引用

- D:\agent-project\target-repos\bottle\bottle.py

## 结构化回报

（待工程师完成后填写）

## 返工与备注

- （无）
