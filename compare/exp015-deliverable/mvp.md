# MVP 编排器分析报告（orchestrator.py）

> 分析对象：`D:\agent-project\architect-engineer\orchestrator.py`（825 行）
> 分析日期：2026-08-19
> 用途：为与 DSH（分布式/共享 harness）架构对照做准备。

---

## 一、整体结构（主要类/函数清单及职责）

该文件是一份"架构师 + 工程师"双模型多 Agent 编排器（MVP），设计蓝本出自
《深入理解 AI Agent》（李博杰）实验 10-2 管理者模式 + 10.4.3.2 提议者-审核者范式。

### 顶层常量
- `ROOT` / `CONFIG`：从 `config.yaml` 加载模型名、端点、价格、工具开关、预算等配置。

### 数据模型（dataclass）
| 符号 | 类型 | 职责 |
|------|------|------|
| `HandoffPacket` | dataclass | 移交包三要素载体：task_id / goal / acceptance / confirmed_facts / artifact_refs / remaining_budget / visited / depends_on。工程师入参。 |
| `TaskCard` | dataclass | 持久化共享任务卡 v0.1：Markdown + YAML frontmatter，含 status( todo/doing/done/rework/escalated )、owner、depends_on、report、notes、search_backend。是跨角色状态流转的载体。 |
| `CostTracker` | class | 成本追踪：按模型累计 token/费用，线程安全追加写 `cost.jsonl`，提供 summary()。 |
| `LLM` | class | 模型客户端（OpenAI 兼容）：读 config 与 API key env，`chat()` 调用并记账；建筑师/工程师各持一个实例。 |
| `Toolbox` | class | 工程师工具集：`read_file` / `write_file` / `list_dir` / `web_search` / `run_command` / `finish`；含路径越界防护、命令黑名单、状态栏、调用计数、查询去重。 |
| `Orchestrator` | class | 主编排器：初始化运行目录与 LLM；方法 `run` / `_schedule` / `run_card` / `run_cards` / `_execute_packet` / `_finish`。 |

### 模块级函数
| 符号 | 职责 |
|------|------|
| `ask_json` | 让模型输出 JSON，失败重试一次并要求只输出 JSON；超限抛错。 |
| `_section` / `_bullets` | 解析任务卡正文中 `## 小节` 与 `- ` 列表。 |
| `load_card` | 解析任务卡文件（frontmatter + 正文）→ `(HandoffPacket, TaskCard)`。 |
| `_http_json` | 最小 HTTP 封装：先直连、失败走本地代理（Clash 7890）；返回(状态码, 响应体)。 |
| `_search_tavily` / `_search_ddg` / `_search_deepseek` | 三个可插拔检索驱动；不可用/无结果返回 None 供降级。 |
| `web_search` | 检索统一入口：auto 走 tavily→ddg 降级链，或按指定 backend 路由。 |
| `run_engineer` | 工程师 ReAct 执行循环（独立上下文，含预算/状态栏/工具调度/纯文本收尾判断）。 |
| `verify` | 验证器：执行 acceptance 中以 `!` 开头的 shell 检查命令，产出执行证据。 |

### 系统 Prompt 常量
- `ENGINEER_SYS`：工程师工作纪律（先读 artifact、跑命令验证、避免臆测、不擅改共享文件、web_search 带时间约束等）。
- `ARCHITECT_PLAN_SYS`：拆任务纪律（信息保真、文件隔离、强制集成卡协议、粒度判据、并行 2-5 卡、Windows 命令约束）。
- `ARCHITECT_REVIEW_SYS`：验收纪律（只输出 veredict JSON，证据失败必须返工）。

---

## 二、编排流程（任务如何被拆分→派发→验收→汇总）

### 主流程（`Orchestrator.run`）
1. **拆任务**：架构师（Kimi K3）通过 `ask_json(ARCHITECT_PLAN_SYS, ...)` 把用户任务拆成 1-5 个子任务（JSON：goal/acceptance/confirmed_facts/artifact_refs/remaining_budget/depends_on）。
2. **建卡**：每个子任务即时落一张 `TaskCard`（status=todo）到 `tasks/card-<id>.md`，保存到 `self.cards`。
3. **审批门（可选）**：`--plan-only` 模式拆卡落盘即停，人审/改卡后再用 `--cards` 放行。
4. **调度**：`_schedule` 是依赖感知的并行调度器（ThreadPoolExecutor，max_workers 默认 3）。
   - 仅当 `depends_on` 全部 done 才派发；
   - 有失败依赖的卡被"冻结"为 escalated（不浪费 token）；
   - 依赖成环/缺失的卡也升级 escalated；
   - 用 `wait(FIRST_COMPLETED)` 循环等待任一张完成再重新评估可派发集合。
5. **单卡执行**：`_execute_packet` 循环执行：
   - 卡片 `doing`（owner=engineer）→ `run_engineer` 执行（工程师 ReAct）→ 结构化回报写入 card.report，owner 改回 architect；
   - **验证器取证**：`verify()` 执行 acceptance 中 `!` 开头的命令，得 `{all_passed, evidence}`；
   - **架构师验收**：`ask_json(ARCHITECT_REVIEW_SYS)` 读 packet + 工程师自述 + 验证证据，判 verdict；
   - **通过**：verdict=pass 且验证 all_passed → card 置 done，返回结论；
   - **返工**：否则 failures++，修复指令写入 card.notes + append 到 packet.confirmed_facts；预算减半（`remaining_budget // 2`，下限 4）重跑；
   - **升级**：连续失败超 `escalation.max_verify_failures` → card 置 escalated（owner=human）交人工。
6. **汇总**：`_finish` 汇总所有 results、卡路径、成本记录，写 `report.json`，打印成本汇总。

### 三种运行模式（`__main__`）
- `python orchestrator.py "任务"`：完整拆卡→执行→验收流程。
- `--plan-only "任务"`：只拆卡，人审后再放行。
- `--card <卡.md>`：直接执行单张手写/外来任务卡（`run_card`，跳过架构师拆任务）。
- `--cards <目录>`：PM 卡盒模式（`run_cards`），读目录下全部卡按依赖批量并行调度。

**核心理念**：完成的判定来自"真实执行的验证证据"，而非模型自称（不共享上下文，k3 不可接续异源历史，用移交包解耦）。

---

## 三、与外部系统的交互点

1. **LLM 调用**：
   - `LLM.chat` 走 OpenAI SDK，`base_url`/模型/价格/API key env 全在 `config.yaml`；
   - 架构师（K3）只做拆任务 + 验收；工程师（DeepSeek V4-Flash）做高频执行；
   - 成本通过 `CostTracker.record` 记账并落盘 `cost.jsonl`。

2. **文件系统**：
   - 读：`config.yaml`、`ROOT` 下资源；任务卡读写 `tasks/card-*.md`；移交包落盘 `handoffs/*.json`；报告落盘 `report.json`。
   - `Toolbox` 严格限定工作目录内写（`_safe`），读允许工作目录 + config 声明的只读根目录（`_safe_read` / `extra_read_roots`）。

3. **子进程**：
   - `Toolbox.execute("run_command")`：`subprocess.run(shell=True)`，有超时与命令黑名单。
   - `verify()`：对 `!` 开头验收命令再做一次 `subprocess.run` 取证（shell=True, cwd=workdir）。

4. **检索 API**：
   - Tavily（付费 API，`_search_tavily`，走 `_http_json`）；
   - DuckDuckGo HTML（免费兜底 `_search_ddg`，注释标注 2026-08 实测被反爬拦截）；
   - DeepSeek 服务端联网（实验性 `_search_deepseek`，需自建兼容端点）；
   - `_http_json` 直连失败自动走本地代理 `127.0.0.1:7890`（Clash）。

---

## 四、与典型 harness 架构相比的差异点 / 缺口清单

1. **无任务/事件持久化存储层**：卡片是文件（Markdown），状态流转靠代码 `touch` 回写文件，无数据库/消息队列。并行调度与状态共享全在进程内 dict。
2. **角色模型固定为 2 个（architect/engineer）**：没有通用 tool-agent / sub-agent 的通用注册与动态实例化机制；多模型扩展需硬改 prompt 与 Orchestrator。
3. **无记忆/历史持久化**：工程师"每次执行"都从全新 context 开始，只靠移交包里的 confirmed_facts/notes 带上次返工原因；跨 run 无向量检索/长期记忆（除 cost.jsonl、卡片文件）。
4. **无统一事件/审计总线**：日志散落在 handoffs/*.json、report.json、卡片文件、stdout，无结构化事件流；`log_handoff` 只落 JSON 文件，不做时序关联。
5. **验证器仅支持"shell 命令"式验收**：`verify()` 只执行 `!` 开头命令，其余文字判据完全交给架构师 LLM 主观评判——没有结构化的单元测试/断言收集器。
6. **无人工审批**内嵌协议（除 escalated 交还人类 owner 外）：`--plan-only` 的审批门是"模式级"而非框架内嵌状态机。
7. **预算控制是粗粒度轮数计费**：`remaining_budget` 只按 ReAct 轮数递减/减半，非 token/时间维度成本约束；无 run-away / 熔断器机制。
8. **无沙箱/隔离运行时**：`run_command` 与 `verify` 均在宿主机 `shell=True` 直跑（仅靠黑名单正则防护）；无容器/VM 隔离、无资源配额（CPU/内存/磁盘）。
9. **无失败重试与幂等保障**：重跑不清理产物，多次 `run_engineer` 可能叠加写入同一文件；无事务式产物提交/回滚。
10. **模型配置强绑定 config.yaml 全局单例**：`CONFIG` 在 import 时一次性加载，无法热更新/按任务卡动态换模型参数（除 search_backend 可按卡覆盖）。
11. **并行上限硬编码可配默认 3**：无自适应扩缩容；调度基于 `FIRST_COMPLETED` 轮询，无抢占/队列优先级。

> 上述列为与"典型 harness（常含统一事件总线、可插拔 agent 注册、隔离沙箱、持久存储、验收/断言框架、人工审批协议）"对比的重要缺口，供 DSH 架构对照参考。
