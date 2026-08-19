---
id: "t_stress"
title: "逆向提取核心控制与仿真逻辑"
status: "todo"
owner: "architect"
created: "2026-08-19T16:50:00"
updated: "2026-08-19T16:50:00"
depends_on: []
budget: 25
---

# 任务卡 t_stress：逆向提取核心控制与仿真逻辑

## 目标

深度遍历开源无人机仿真控制仓库 Quadcopter_SimCon（位于 D:\agent-project\target-repos\Quadcopter_SimCon，约 31 个 Python 文件），独立完成三件事：

1. 找出实现底层非线性动力学仿真模型的核心代码文件（状态方程、力/力矩计算、数值积分在哪里）；
2. 逆向梳理出其中的串级 PI 控制系统逻辑——有哪几级控制环、每环的输入/输出/被控量、环与环之间的级联关系、PI 增益在哪里定义；
3. 将提取出的控制链路结构输出到 control_architecture.md（相对路径，写在当前工作目录根部）。

文档要求：每个结论必须附具体源码文件路径（相对仓库根的路径，如 Simulation/ctrl.py）+ 尽量给出类/函数名；读不懂的部分如实标注「未读懂」，禁止编造。

## 验收标准

- !python -c "import pathlib; p=pathlib.Path('control_architecture.md'); assert p.exists() and p.stat().st_size>2500, 'file missing or too small'"
- !python -c "import pathlib; t=pathlib.Path('control_architecture.md').read_text(encoding='utf-8'); [(_ for _ in ()).throw(AssertionError('missing: '+k)) for k in ['串级','PI','ctrl.py','quad.py'] if k not in t]"
- !python -c "import pathlib,re; t=pathlib.Path('control_architecture.md').read_text(encoding='utf-8'); paths=re.findall(r'[\w\-/\\\\ ]+\.py', t); assert len(paths)>=5, 'too few source file references'"
- !python -c "import pathlib,re; base=pathlib.Path(r'D:\agent-project\target-repos\Quadcopter_SimCon'); t=pathlib.Path('control_architecture.md').read_text(encoding='utf-8'); paths=set(re.findall(r'(?:Simulation|PyDy Scripts)[\w\-/\\\\ ]*?\.py', t)); missing=[p for p in paths if not (base/p).exists()]; assert not missing, f'引用了不存在的文件: {missing[:3]}'"
- 架构师审查：文档必须清晰说明控制系统的串级结构（几级环、级联关系），且所有引用的仓库内源码路径必须真实存在

## 已确认事实与约束

- 运行环境是 Windows，探索命令只能用 python 或 Windows 原生命令（dir/type），严禁 Unix 命令
- 目标仓库在工作目录之外，用 read_file / list_dir 以绝对路径只读访问（已授权）；写入只能在当前工作目录内
- 你有 25 轮预算——这是深读任务，请规划好探索顺序：先 list_dir 摸清结构，再按相关性从大到小读文件，不要平均用力
- 本任务只写 control_architecture.md，禁止写其他成果文件

## 产物引用

- D:\agent-project\target-repos\Quadcopter_SimCon\Simulation
- D:\agent-project\target-repos\Quadcopter_SimCon\PyDy Scripts

## 结构化回报

（待工程师完成后填写）

## 返工与备注

- （无）
