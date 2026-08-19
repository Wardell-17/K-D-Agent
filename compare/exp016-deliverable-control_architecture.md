# Quadcopter_SimCon 控制系统架构逆向分析

> 分析对象：开源仓库 `Quadcopter_SimCon`（约 31 个 Python 文件）。
> 本文件梳理：① 底层非线性动力学仿真模型核心代码；② 串级 PI 控制系统逻辑；
> ③ 控制链路结构。所有结论均附仓库内相对路径与类/函数名。

---

## 0. 总体框架（运行入口与数据流）

主仿真入口为 `Simulation/run_3D_simulation.py` 的 `quad_sim(t, Ts, quad, ctrl, wind, traj)`，
每一时间步的执行顺序为（`quad_sim` 内三行）：

1. `quad.update(t, Ts, ctrl.w_cmd, wind)` —— 用上一时间步计算出的电机指令推进动力学；
2. `traj.desiredState(t, Ts, quad)` —— 生成期望状态 `sDes`（`Simulation/trajectory.py::Trajectory.desiredState`）；
3. `ctrl.controller(traj, quad, sDes, Ts)` —— 计算下一时间步的电机指令 `ctrl.w_cmd`。

关键类：
- `Simulation/quadFiles/quad.py::Quadcopter` —— 动力学模型；
- `Simulation/ctrl.py::Control`          —— 级联控制器；
- `Simulation/trajectory.py::Trajectory` —— 期望状态/轨迹生成；
- `Simulation/quadFiles/initQuad.py`     —— 物理参数与混合器矩阵 `sys_params()` / `makeMixerFM()`；
- `Simulation/utils/mixer.py::mixerFM`   —— 期望推力/力矩 → 电机转速指令；
- `Simulation/config.py`                 —— 坐标系（NED/ENU）与陀螺进动开关。

---

## 1. 底层非线性动力学仿真模型核心代码

### 1.1 状态方程（微分方程/动力学）—— 核心文件
- **文件**：`Simulation/quadFiles/quad.py`
- **类/方法**：`Quadcopter.state_dot(self, t, state, cmd, wind)`
- **说明**：这是整个动力学模型的核心。状态向量 `state` 共 **21 维**：
  - `state[0:3]`  位置 (x,y,z)
  - `state[3:7]`  姿态四元数 (q0,q1,q2,q3)
  - `state[7:10]` 线速度 (xdot,ydot,zdot)
  - `state[10:13]` 体轴角速度 (p,q,r)
  - `state[13:20]` 4 个电机的角速度 (wM1..wM4) 与角加速度 (wdotM1..wdotM4)
- `state_dot` 中把 `MM*xdot = RHS` 的解析解（来自 PyDy/Kane 法推导）直接硬编码为 `DynamicsDot` 数组，
  包含 6 自由度刚体动力学（线加速度、角加速度）+ 四元数运动学 + 风阻力。
- 姿态（单位四元数导数）：
  `qdot = [-0.5*p*q1 - 0.5*q*q2 - 0.5*q3*r, ...]`
- 体轴角加速度（NED 支路，`state_dot` 内 `DynamicsDot`）：
  - roll:  `((IByy-IBzz)*q*r + uP*IRzz*(wM1-wM2+wM3-wM4)*q + (ThrM1-ThrM2-ThrM3+ThrM4)*dym)/IBxx`
  - pitch: `((IBzz-IBxx)*p*r + uP*IRzz*(wM1-wM2+wM3-wM4)*p + (ThrM1+ThrM2-ThrM3-ThrM4)*dxm)/IByy`
  - yaw:   `((IBxx-IByy)*p*q - TorM1+TorM2-TorM3+TorM4)/IBzz`
  - 其中 `uP` 由 `config.usePrecession` 控制是否计入转子陀螺进动。

### 1.2 力 / 力矩计算
- **文件**：`Simulation/quadFiles/quad.py`
- **类/方法**：`Quadcopter.forces(self)`
  - 每个转子的推力 `thr[i] = kTh * wMotor[i]^2`
  - 每个转子的阻力矩 `tor[i] = kTo * wMotor[i]^2`
- 在 `state_dot` 内部也直接计算 `thrust = kTh*wMotor^2` 与 `torque = kTo*wMotor^2`，
  并按其几何布局（M1 前左、顺时针编号）合成到各轴（dxm/dym 力臂）。
- 风与气动阻力：`state_dot` 中调用 `wind.randomWind(t)`（`Simulation/utils/windModel.py::Wind`），
  以 `Cd` 阻力系数对线加速度方程叠加二次气动阻力项。

### 1.3 数值积分
- **文件**：`Simulation/quadFiles/quad.py`
- **类/方法**：`Quadcopter.__init__` 与 `Quadcopter.update`
- 使用 SciPy `scipy.integrate.ode`（自带 Dormand–Prince `dopri5`）作为数值积分器：
  ```python
  self.integrator = ode(self.state_dot).set_integrator('dopri5', first_step='0.00005', atol='10e-6', rtol='10e-6')
  ```
- 每步 `update` 以固定采样 `Ts`（默认 0.005s）调用 `integrator.integrate(t, t+Ts)` 推进状态。

### 1.4 电机动力学（二阶系统）
- **文件**：`Simulation/quadFiles/quad.py`（`state_dot` 内 `wddotM1..wddotM4`）
- 电机角速度/角加速度额外 8 个状态，用二阶系统表示：
  `wddot = (-2*damp*tau*wdot - w + kp*uMotor)/(tau^2)`，
  参数 `tau/damp/kp` 定义于 `Simulation/quadFiles/initQuad.py::sys_params()`。

### 1.5 参数来源
- **文件**：`Simulation/quadFiles/initQuad.py`
  - `sys_params()`：质量 mB=1.2 kg、臂长 dxm/dym=0.16 m、惯量张量 IB、
    转子惯量 IRzz、推力系数 kTh、扭矩系数 kTo、Cd、min/maxThr、min/maxWmotor 等；
  - `makeMixerFM(params)`：生成“推力+F/M → 电机转速”混合矩阵 mixerFM 及其逆 mixerFMinv；
  - `init_cmd` / `init_state`：悬停初始指令与初始 21 维状态。

### 1.6 动力学方程的“……源”说明（PyDy 脚本）
- `PyDy Scripts/00 - Basic/Quad_3D_frd_NED_Quat.py`（以及同目录 Euler 版、ENU 版、
  `01 - Added Gyroscopic Precession/`、`02 - Added Wind and Aero Drag/`）用 SymPy/PyDy 的
  Kane 法推导 Mass Matrix (`MM`) 与 RHS，解析得到状态导数；
  `state_dot` 中的 `DynamicsDot` 即这些解析式的手工移植版本（README 已说明“copied from the corresponding PyDy script”）。
- 说明：这些 PyDy 脚本是动力学方程的“符号推导源”，真正的数值仿真/积分在 `quad.py`。

---

## 2. 串级 PI（级联）控制系统逻辑

控制器全部位于 **`Simulation/ctrl.py`**，类 `Control`；
`Control.controller(traj, quad, sDes, Ts)` 根据 `traj.ctrlType`
（`"xyz_pos"` / `"xy_vel_z_pos"` / `"xyz_vel"`）选择环的启用方式，
但四环级联骨架一致。

### 级联结构总览（外环 → 内环）
```
 位置环(P) → 速度环(PD,可选I) → 推力求姿态(无反馈) → 姿态环(P) → 角速度环(PD) → 混合器 → 电机指令
 (期望位置)   (速度设定)        (期望姿态四元数)      (角速度设定)   (期望力矩)     (电机转速)
```

### 2.1 第 1 级 —— 位置控制环（P 增益）
- **方法**：`Control.z_pos_control`（Z/高度）、`Control.xy_pos_control`（水平 XY）
- **输入**：期望位置 `self.pos_sp`，反馈为当前 `quad.pos`
- **输出**：速度设定 `self.vel_sp`（叠加到期望速度上）
- **被控量**：位置 (x,y,z)
- **增益**：`pos_P_gain`（文件头部定义为 `Pz=Py=Px=1.0`）

### 2.2 第 2 级 —— 速度控制环（PD 增益 + 可选 I）
- **方法**：`Control.z_vel_control`（D 方向推力）、`Control.xy_vel_control`（NE 方向推力）
- **输入**：期望速度 `self.vel_sp`，反馈 `quad.vel` 与 `quad.vel_dot`
- **输出**：推力设定 `self.thrust_sp`（向量，即推力大小与方向）
- **被控量**：线速度 (xdot,ydot,zdot)
- **增益**：`vel_P_gain`（Pxdot=Pydot=5.0、Pzdot=4.0）、`vel_D_gain`（0.5）、`vel_I_gain`（5.0）
- 悬停推力 `m*g` 作为前馈（Feed-Forward）在 `z_vel_control` 中并入。
- 积分项受 `quad.params["useIntergral"]`（`initQuad.py::sys_params()`，默认 `bool(False)`）
  控制是否启用，且带抗饱和（anti-windup）逻辑。

### 2.3 第 3 级 —— 推力求姿态（期望姿态，无 PID 反馈）
- **方法**：`Control.thrustToAttitude`
- **逻辑**：由推力设定方向构造期望机体 Z 轴，结合期望偏航 `self.eul_sp[2]`（来自轨迹），
  通过向量叉乘构造期望旋转矩阵，再用 `Simulation/utils/quaternionFunctions`（`utils.RotToQuat`）
  得到**完整期望四元数** `self.qd_full`。
- 说明：这一级不是传统“控制器环”，而是把推力向量几何映射为期望姿态，属链路的中间环节。

### 2.4 第 4 级 —— 姿态（四元数误差）控制环（P 增益）
- **方法**：`Control.attitude_control`
- **输入**：当前姿态四元数 `quad.quat`（体坐标 DCM 的 e_z 轴）与期望姿态（由第 3 级求得）
- **输出**：期望角速度设定 `self.rate_sp`
- **被控量**：姿态（roll/pitch/yaw，以四元数误差表示）
- **增益**：`att_P_gain`（Pphi=Ptheta=8.0、Ppsi=1.5；`setYawWeight` 中会把 Ppsi 折算为 roll/pitch 均值）
- 内部计算“缩减期望四元数 `qd_red`”（不含偏航）与“混合期望四元数 `qd`”，
  再按 `rate_sp = (2*sign(qe0)*qe[1:4])*att_P_gain` 形成角速度设定，并在偏航轴叠加 yaw 前馈。

### 2.5 第 5 级 —— 角速度（Rate）控制环（PD 增益）
- **方法**：`Control.rate_control`
- **输入**：期望角速度 `self.rate_sp`，反馈 `quad.omega` 与 `quad.omega_dot`
- **输出**：期望力矩指令 `self.rateCtrl`（三维，后续交给混合器）
- **被控量**：体轴角速度 (p,q,r)
- **增益**：`rate_P_gain`（Pp=Pq=1.5、Pr=1.0）、`rate_D_gain`（Dp=Dq=0.04、Dr=0.1）

### 2.6 混合器（Mixer）—— 由推力/力矩到电机转速
- **文件**：`Simulation/utils/mixer.py`，方法 `mixerFM(quad, thr, moment)`
- **输入**：期望推力大小 `norm(self.thrust_sp)` 与 `self.rateCtrl`（力矩）
- **输出**：4 个电机转速指令 `self.w_cmd`
- 计算：`w_cmd = sqrt(clip(inv(mixerFM) * [thr, Mx, My, Mz]))`，
  `mixerFM` 与 `mixerFMinv` 在 `initQuad.py::makeMixerFM / sys_params` 中生成。
- 该输出 `w_cmd` 即下一时间步 `quad.update` 使用的电机指令 `cmd`，从而闭合级联链路。

### 2.7 饱和与约束（贯穿多级）
- `saturateVel`（`Simulation/ctrl.py`）：对速度设定限幅（`velMax`/`velMaxAll`）。
- 速度环中带推力限位、`tiltMax` 倾斜限制、抗饱和逻辑。
- 姿态环限幅角速度设定 `rateMax`；混合器内对电机转速限幅 `minWmotor/maxWmotor`。

---

## 3. 控制链路数据流（直通关系）总结

`期望位置(pos_sp) → [位置环 P] → 期望速度(vel_sp) → [速度环 PD+I] → 期望推力(thrust_sp)`
`→ [thrustToAttitude] → 期望四元数(qd) → [姿态环 P] → 期望角速度(rate_sp)`
`→ [rate环 PD] → 期望力矩(rateCtrl) → [mixerFM] → 电机转速指令(w_cmd) → [quad.update 动力学]`

增益全部定义在 `Simulation/ctrl.py` 顶部（各 `*_P_gain / *_D_gain / *_I_gain`），
无需猜测；其它可调约束（maxThr、tiltMax、rateMax 等）亦同文件定义。

---

## 4. 未读懂 / 存疑之处（如实标注）

- `Simulation/ctrl.py::attitude_control` 中关于 `qd_mix` 的合成公式较复杂，
  尤其是 `clip` 与 `arcsin/arccos` 的 Yaw 权重混合（`setYawWeight` 对 `att_P_gain[2]` 的修改），
  我理解其意图是“在偏航权重下把完整与缩减四元数插值混合”，但具体几何含义未能 100% 复述。
- `Simulation/trajectory.py` 中 `minSomethingTraj*` 系列多项式轨迹的系数矩阵推导细节较长，
  对串级控制链路本身无直接影响（仅影响期望值生成），故未逐行精读其约束矩阵装配。
- `Simulation/utils/quaternionFunctions.py / rotationConversion.py` 中部分四元数/旋转辅助函数
  的具体推导未逐一核对（不影响控制级联结论）。

---

## 5. 参考文件清单（相对仓库根路径）

- `Simulation/ctrl.py` —— 串级控制器（核心，任务主线）
- `Simulation/quadFiles/quad.py` —— 动力学状态方程 / 力-力矩 / 数值积分
- `Simulation/quadFiles/initQuad.py` —— 参数、混合矩阵、悬停指令
- `Simulation/utils/mixer.py` —— 期望推力/力矩 → 电机转速
- `Simulation/utils/windModel.py` —— 风模型
- `Simulation/trajectory.py` —— 期望状态/轨迹生成
- `Simulation/run_3D_simulation.py` —— 主运行入口与数据流
- `Simulation/config.py` —— 坐标系/进动开关
- `PyDy Scripts/00 - Basic/Quad_3D_frd_NED_Quat.py` —— 动力学方程符号推导源（Kane 法）
