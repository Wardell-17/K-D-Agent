# L 级实战题库（分层基线 · 重型样本）

> 选题纪律（防数据失真）：
> 1. **防"伪 L 级"**：每题必须含跨模块依赖 + 集成约束，逼架构师批 >25 轮预算
> 2. **防 Token 浪费**：复杂度体现在思考与修改深度，不靠遍历大文件
> 3. **硬断言验收**：全部用可真实执行的 pytest / 脚本断言，禁止 `assert exists` 水验收
>
> 仓库已预落盘到 `D:\agent-project\target-repos\`（工程师不许自己 clone）。
> 基线已验证：httpbin 70 passed / sortedcontainers 299 passed / Quadcopter ctrl 模块可导入。

---

## L-01 · 飞控串级控制逆向梳理（仓库：Quadcopter_SimCon）

```
目标仓库在 D:\agent-project\target-repos\Quadcopter_SimCon（Python，四旋翼仿真，
控制代码参考 PX4 架构）。任务分两层，必须都完成：

【分析层】逆向梳理 Simulation/ 目录下的控制链路，输出 control_architecture.md（当前目录即产物区，不要加 workspace/ 前缀），
必须包含：位置环→速度环→姿态环→角速率环的串级结构说明、每级对应的源码文件与函数名
（精确到 ctrl.py / trajectory.py / utils/mixer.py 等具体路径）、控制量如何从期望位置
一路变换到四个电机转速的完整链路。

【集成层】编写 verify_cascade.py 脚本（当前目录），真实导入 Simulation/ctrl.py 与相关模块，
用合成状态量驱动控制链，数值验证串级结构：给定期望位置，断言控制链输出
(1) 总推力为有限正数 (2) 期望力矩三分量均为有限数 (3) 经 mixer 分配后四个电机
指令均在物理约束内。脚本退出码必须为 0。

验收：
!C:\Python314\python.exe verify_cascade.py
!C:\Python314\python.exe -c "c=open('control_architecture.md',encoding='utf-8').read(); assert 'ctrl.py' in c and 'mixer' in c and '串级' in c; print('OK')"

背景约束：工作目录是 architect-engineer/，仓库路径要写绝对路径；
所有 python 命令必须用 C:\Python314\python.exe 全路径（管道环境 PATH 里另有托管 Python，缺 numpy/pytest）；
sys.path 需插入 Simulation/ 目录才能 import ctrl；
所有结构结论必须来自源码实读，禁止凭常识编造 PX4 知识。
```

## L-02 · Web 服务跨层新功能（仓库：httpbin，基线 70 passed）

```
目标仓库在 D:\agent-project\target-repos\httpbin（Flask 小型 Web 服务）。
完成一个跨层功能修改，涉及至少三个文件：

1. 在 httpbin/helpers.py 新增辅助函数：解析请求查询参数中的 delay 秒数，
   钳制到 [0, 10] 区间并返回 float（非法输入回退 0）
2. 在 httpbin/core.py 新增端点 GET /delayed-echo：调用上述辅助函数取得 delay，
   睡眠后以 JSON 返回 {"delay": 实际值, "args": 请求查询参数, "headers": 请求头 dict}
3. 在 tests/ 新增测试文件，覆盖：正常延迟参数、非法参数回退、超过 10s 被钳制
   （测试里 monkeypatch time.sleep 避免真实等待）

验收（在仓库根目录执行，必须全绿）：
!cd /d D:\agent-project\target-repos\httpbin && C:\Python314\python.exe -m pytest tests -q

背景约束：不许破坏既有 70 条测试；代码风格对齐仓库现状；
endpint 注册方式参照 core.py 既有路由写法。
```

## L-03 · 算法库约束重构（仓库：python-sortedcontainers，基线 299 passed）

```
目标仓库在 D:\agent-project\target-repos\python-sortedcontainers（纯 Python 有序容器库）。
完成一次保持行为不变的重构 + 测试加固，涉及至少两个模块：

1. 阅读 src/sortedcontainers/sortedlist.py，找出 add()/update() 中重复出现的
   "定位插入位置 + 展开内部列表"逻辑，提取为私有辅助方法并在两处复用
2. 同步检查 sorteddict.py / sortedset.py：若存在同模式重复代码，一并复用新辅助方法
   （不允许改变任何公开 API 签名与行为）
3. 在 tests/ 新增测试：针对重构路径补边界用例（空容器插入、单元素、重复值批量 update）

验收（在仓库根目录执行，必须全绿）：
!cd /d D:\agent-project\target-repos\python-sortedcontainers && C:\Python314\python.exe -m pytest tests -q --ignore=tests/benchmark_scale.py

背景约束：行为不变是第一纪律——299 条既有测试全绿才算完；
重构必须有真实去重效果（架构师会审查 diff，禁止只改注释凑数）。
```

---

## 执行记录

| 题号 | run | 预算档位 | 成本 | 验收 | 实验记录 |
|---|---|---|---|---|---|
| L-01 | | | | | |
| L-02 | | | | | |
| L-03 | | | | | |
