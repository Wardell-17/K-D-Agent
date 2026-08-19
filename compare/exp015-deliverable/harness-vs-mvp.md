# DSH Harness vs 我方 MVP：架构对照与吸收路线图

> 摘要：本文基于 four 份中间成果（arch-layers / startup / subsystems / mvp）将 DSH（DeepSeek Harness，`D:\agent-project\harness-src`）与我方 `orchestrator.py` 作对照。DSH 是一个以 cordis 依赖注入为骨架、按"基础设施→核心→能力→装配"分层的多包 harness；我方 MVP 是一个 825 行的单体双模型编排脚本。第 1 章压缩复述 DSH 架构与启动链路（附源码证据）；第 2 章对 llm/credentials/subagent/preset 四个子系统逐一做「DSH怎么实现 vs MVP怎么实现 vs 谁更优」三段对照；第 3 章提炼至少 4 条值得吸收进 MVP 路线图的机制，每条标注吸收价值与改造成本。全部事实性结论均可回溯至 findings 内源码路径，未引入 findings 之外的新断言。

---

## 1. DSH 总体架构与启动链路

### 1.1 分层架构（依据 arch-layers.md）

DSH 是 monorepo（根 `pnpm-workspace.yaml`，`packages/*/*`、`apps/*`、`vendor/*`），分层依据是**依赖方向**，不按目录名臆测。沿依赖方向从底层到入口共七层：

- **第 0 层 基础设施（叶子）**：`packages/util/launch-environment`、`packages/util/atomic-write`、`packages/storage/storage`、`packages/host/webserver` 等，peerDeps/deps 仅 `cordis`+`dsh-invariants`（+`schemastery`）。
- **第 1 层 共享不变式与引导**：`packages/runtime-diagnostics/invariants`（`dsh-invariants`，几乎每包 peerDep）与 `packages/boot`（`dsh-app-boot`）。
- **第 2 层 核心层 core/**：`core/agent`（peerDeps `dsh-llm`/`dsh-session`/`dsh-scope`）、`core/agent-loop`、`core/session`、`core/tools`、`system-prompt`、`scope` 构成产品 API 主干。
- **第 3 层 会话数据平面**：`session/*`（`session-persistence`、`session-persistence-jsonl`/`sqlite`、`session-projection*`、`session-telemetry*`）与 `storage/*` 的投影/检索/压缩。
- **第 4 层 能力层**：`llm/`、`credentials/`、`subagent/`、`fs/`、`workflow/`、`shell/`、`sandbox/` 等。每个能力 = **seam（`dsh-<cap>` Service Definition）+ provider（`<cap>-local`/`<cap>-<backend>`）+ 模型工具（`tool-<cap>`）** 三元结构，该约束写在 `packages/AGENTS.md`（`2026-06-13-capability-seams.md`）。
- **第 5 层 Web 宿主**：`host/*`（`host-webserver`「knows no harness concepts」）、`client/*`、`api/*`、`typert/*`。
- **第 6 层 装配层 apps/**：`apps/cli`（`@deepseek-ai/dsh`，bin 名 `dsh`）dependencies 横跨所有层，`apps/web`（`vite build over the dsh-client-web`）只依赖 client-react + host 静态。apps 是**组合包**，不定义新能力，只把各 seam+provider+consumer 组装运行。

> 发现两处 findings 间的衔接口径：arch-layers.md 将 `storage` 归第 0 层（叶子），但又在第 3 层列出 `storage/*`；subsystems.md 未涉 storage。本文如实标注：arch-layers 认为 `packages/storage/storage` 本身是零依赖叶子中枢，而 `storage-{json,sqlite}` 是挂在其上的后端 extension，二者复用但在不同子句。此为 arch-layers 自身表述，非两文件矛盾。

### 1.2 启动链路（依据 startup.md）

`apps/cli/src/bin.ts` 为入口，`parseDshArgs`（`apps/cli/src/args.ts`，class `Command`）解析启动器自有 flag，按 `invocation.mode` 分发：`profile`/`plugin`/`dump-config`，主链路走 **profile** 分支 `runProfile`（`apps/cli/src/profile-boot.ts`）。`runProfile` 内 `composeProfile` 拼接 patch 层（bundle→profile 自身 `cordis.patch.yml`→全局 home→`--patch` overlay→telemetry），`createProcessShutdown`（`apps/cli/src/process-shutdown.ts`，`PROCESS_SHUTDOWN_TIMEOUT_MS=5_000`）建立关停控制器，随后 `boot(NAME, rootConfig, …)`。

主加载循环在 `packages/boot/app-boot/src/index.ts` 的 `boot()`：`new Context()`（cordis）→ `ctx.plugin(Loader)`（`@deepseek-ai/cordis-plugin-loader`）→ `prepare?.(ctx)`（注入 `DSH_LAUNCH_ENVIRONMENT_KEY`/`provideCmdline`）→ `mountRootInclude`（装载根 `cordis.yml` 并 include patch 层）→ `ctx.get('loader')?.await()` + `assertEntriesActivated` 等待 plugin 树 settle 并核验激活项。`loadLayeredEnv` 装载 `.env` 分层快照（inherit›项目›Harness home），`resolveConfigPath` 在 `$DSH_SNAPSHOT=replay` 时切到 `cordis.snapshot.yml`。

---

## 2. 四子系统对比

### 2.1 llm

**DSH 怎么实现（subsystems.md）**：LLM 层在 `packages/llm`。抽象核心 `LlmAdapter` 基类（`packages/llm/llm/src/types.ts`），provider 继承它并实现 `providerInfo/listModels/resolveModel/stream/resolveRetryPolicy`；路由经 `ctx.llm.registerAdapter([PROVIDER], adapter)` 注册。真实适配器：`DeepSeekAdapter`（`packages/llm/llm-deepseek/src/adapter.ts`，直连 OpenAI-compatible chat-completions，provider 路由 `deepseek-official`，baseURL `https://api.deepseek.com`，`stream()` 每次"一次解析、全程冻结"连接事实与 key）；`PiAiAdapter`（`packages/llm/llm-pi-ai/src/adapter.ts`，基于 pi-ai，一次 resolution 产生不可变 `PiAiSnapshot`）。**记账缺口实证**：web 搜索后端不在 llm 包而在 `packages/web/web-search-deepseek/src/provider.ts`（`DeepSeekSearchProvider`，POST `/anthropic/v1/messages` + `deepseek-v4-flash` + `web_search_20250305`），且明示"不使用 `ctx.llm`"；它只发射 `web/deepseek-search-llm-request` 事件（无 `usage`），而 `TokenMeter`（`packages/llm/token-meter/src/index.ts`）只在 `assistant/message` 且 `data.usage !== undefined` 时建 anchor 记账——所以检索那次 model turn 不进账单。

**我们 MVP 怎么实现（mvp.md）**：`LLM` 类（`LLM.chat`）走 OpenAI SDK，`base_url`/模型/价格/API key env 全在 `config.yaml`；架构师（Kimi K3）与工程师（DeepSeek V4-Flash）各持一个 `LLM` 实例；成本经 `CostTracker.record` 落盘 `cost.jsonl`。检索由 `web_search` 统一入口走 `_search_tavily`/`_search_ddg`/`_search_deepseek` 三个驱动。

**谁更好**：DSH 更好。MVP 的 `LLM` 是单点客户端（config.yaml 全局单例，`CONFIG` 在 import 时一次性加载，无法热更新/按卡动态换模型）；DSH 把 LLM 做成 provider 可注册的路由 seam（`registerAdapter`/`registerConfigurableProviders`），且把"连接事实与 key 每次请求冻结解析"作为显式防御。MVP 的搜索与计费耦合在内部驱动；DSH 则暴露"搜索不经过 LLM 记账"的原生命口——虽然这是缺陷，但至少边界清晰、可定位。MVP 应向 DSH 学"provider 注册 + 配置热更新"，但不必照搬其记账缺口的撞车语义。

### 2.2 credentials

**DSH 怎么实现（subsystems.md）**：`packages/credentials/credentials/src/index.ts` 定义 `CredentialProvider extends Service('credentials')`，抽象方法 `resolve/describe/set/unset`；配置面只携带 CredentialRef（环境变量名），真实值归 provider。`packages/credentials/credentials-local/src/index.ts` 的 `LocalCredentialProvider.resolve()` 顺序：inherited 环境变量 › `$DSH_HOME/.credentials.yaml` › `<cwd>/.env` › `$DSH_HOME/.env`，全空返回 undefined。**关键语义**（`packages/llm/llm-deepseek/src/index.ts` 的 `resolveApiKey`）：只要 `credentials` 服务被加载但该 ref 无记录（resolve 返回 undefined），代码**不会**走 `else` 的环境变量分支，直接 `throw LlmError('...no API key...','MISSING_CREDENTIAL')`；环境变量回落只在"credentials 服务完全未注册"时才生效。web 搜索侧 `web-search-deepseek/src/provider.ts` 的 `apiKey()` 无 key 抛 `WEB_PROVIDER_CREDENTIAL_MISSING`。

**我们 MVP 怎么实现（mvp.md）**：API key 经环境变量读取（OpenAI SDK base_url/API key env 在 `config.yaml`）。没有专门的 credentials 抽象服务；`LLM` 直接用自己的配置与 env 取 key。

**谁更好**：DSH 更严谨但有"坑"。DSH 的 credentials 抽象（provider 拥有真实值、配置面只存 ref）比 MVP 的"config + env 直取"更可扩展（多 provider、可写托管 `.credentials.yaml`）。但其"MISSING_CREDENTIAL 不回落环境变量"是易踩的边界行为，subsystems.md 已标为与用户实测一致。MVP 现阶段规模小，直取 env 更简单；但要吸收 DSH 的教训：若引入 credentials 抽象，务必在同一层内显式收敛回落语义，避免"存在服务但无记录就硬抛"的隐性切换。

### 2.3 subagent

**DSH 怎么实现（subsystems.md）**：`tool-subagent`（`packages/subagent/tool-subagent/src/index.ts`）暴露 `subagent` 工具，调用 `ctx.subagents.start(provider,{label,prompt,parent,agentOptions,persona,toolFilter,maxDepth,...})`；前台 `settleForegroundRun`，后台 `startContinuable`/jobs。每个子代理会话打 `subagent/descriptor` 持久化身份（`packages/subagent/subagent/src/descriptor.ts` 的 `snapshotSubagentDescriptor`，含 `mode:'one-shot'|'continuable'`、`provider`、continuable 时的 toolFilter/persona/model）。**工具权限阉割实证**：`toolFilter`（`ToolRestriction{allow?,deny?}`）既写请求也落续盘描述符；被过滤工具"从 prompt 消失且执行被拒"；`maxDepth` 默认 3（0 禁止派工），provider 须具备 `depthLimit` capability。"spawn 后不干活"很可能是 `toolFilter` 过严（如 `allow:[]` 否掉所有工具）或 `maxDepth/capability` 不匹配；Schemastery 默认 `{allow:[]}` 会否掉全部工具，代码特意 `.default(undefined)` 规避。

**我们 MVP 怎么实现（mvp.md）**：角色模型**固定为 2 个**（architect/engineer），没有通用 tool-agent/sub-agent 的注册与动态实例化机制；多模型扩展需硬改 prompt 与 `Orchestrator`。并行调度在进程内，唯一的"子代理"概念是工程师/架构师的职责划分，无真正的递归派工、无 `toolFilter`/`maxDepth`/persona 分层。

**谁更好**：DSH 明显更完备。DSH 有通用 subagent seam + 递归派工 + 工具权限分层 + 持久化描述符，MVP 只是双角色硬编码。但**就 MVP 的借鉴价值而言**，DSH 的 `toolFilter` 阉割陷阱是极有价值的反面教材：即便 MVP 想引入子代理做任务拆分，也需显式定义"子代理可用工具集"并默认全量/合理默认，避免 `allow:[]` 把子代理做废。MVP 可先吸收"工具权限边界 + 递归深度上限"两个概念，不必照搬完整 descriptor 持久化。

### 2.4 preset

**DSH 怎么实现（subsystems.md）**：`packages/preset/agent-presets/src/discovery.ts`：`COMPOSITION_FILE='agent.cordis.yml'`，`USER_PRESET_DIR='.agent-presets'`。`discoverPresets(roots)` 按 root 优先级扫描（前一个 root 的同 id 覆盖，first-root-wins）；`scanRoot` 只认含 `PRESET_ID` 且有 `agent.cordis.yml` 的目录；`entryListProblem`/`compositionProblem` 校验顶层是 plugin row 列表、每行带 `name`、`group:true` 递归校验。合并是**先到先得**（同一 id 只留最优先 root 那份，不深合并）。挂载在 `mount.ts` 装载 `agent.cordis.yml` composition 进运行时，`session.ts` 处理会话级生效，metadata 经 `metadata.ts`（`readPresetMetadata`），authoring 在 `authoring.ts`。工具白名单不是 preset 自定义机制，而是 preset 下发 `toolFilter`（allow/deny）由工具面装配 agent 时施加；未知工具名 fail-loud 发生在 agent 装配期（`tool-subagent` mount 时 `unknown names fail startup`）。

**我们 MVP 怎么实现（mvp.md）**：无 preset/配置预设概念。配置只来自 `config.yaml`（模型名、端点、价格、工具开关、预算）；`search_backend` 可按卡覆盖，其余全局单例；无 profile/预设合并、无版本化配置模板。

**谁更好**：DSH 更好。DSH 的 preset 提供了"多文件配置合并（带优先级、先到先得）+ 校验 + 服务端 authoring"，MVP 只有单文件 config.yaml。MVP 的 `--plan-only` 审批门算半个"预设 profile"（人审放行），但缺少合并与校验。MVP 短期内可受益于"按任务卡/角色提供预设配置片段并合并"，吸收 DSH 的先到先得 + 结构校验；但需注意 DSH 的 `entryListProblem` 只做浅校验、工具名校验延后到装配期——这也是一个"错误定位延迟"的可借鉴教训。

---

## 3. 总结：DSH 哪些机制值得吸收进 MVP 路线图

> 至少四条，每条给出吸收价值与改造成本（依据四份 findings 中的证据）。

1. **能力 seam + provider + consumer-工具 的可插拔注册（llm 层）**。DSH 用 `registerAdapter([PROVIDER], adapter)` 让新模型 provider 即插（`packages/llm/llm/src/types.ts` 的 `LlmAdapter`；`packages/llm/llm-deepseek/src/adapter.ts`）。MVP 的 `LLM` 是 config 全局单例。**价值**：让"换模型/加 provider"从硬改 `Orchestrator` 变成配置式注册，契合 MVP 拆卡时按卡选模型的需求。**成本**：中等——需把 `LLM` 拆成抽象接口 + provider 注册表，修改 `run_engineer`/架构师调用点与 `config.yaml` 解析，约改动 `orchestrator.py` 的 LLM 段与配置加载段。

2. **配置 profile/preset 合并与校验（preset 层）**。DSH 的 `discoverPresets` 按 root 优先级先到先得合并 `agent.cordis.yml`，并用 `entryListProblem`/`compositionProblem` 校验（`packages/preset/agent-presets/src/discovery.ts`）。MVP 只有单文件 `config.yaml`。**价值**：支持"按卡/角色预设配置片段"，把 `--plan-only` 的人审门升级为"多配置来源 + 结构校验 + 先到先得"。**成本**：中低——新增一个配置合并层与校验函数，复用现有 `config.yaml` 读入，不必引入完整 cordis patch 机制。

3. **子代理工具权限边界 + 递归深度上限（subagent 层）**。DSH 的 `toolFilter`（`ToolRestriction{allow?,deny?}`）与 `maxDepth`（默认 3）约束子代理可用工具与派工深度（`packages/subagent/tool-subagent/src/index.ts`、`packages/subagent/subagent/src/descriptor.ts`），且已知反例是 `allow:[]` 会把子代理做废（Schemastery 默认须 `.default(undefined)` 规避）。**价值**：MVP 若引入递归子任务派工，必须先定"子代理工具白名单 + 深度上限"，避免失控递归/工具被无故阉割。**成本**：若只加"边界与上限"概念则低（在 `run_engineer`/`_schedule` 加约束字段）；若要完整 descriptor 续盘持久化则高。

4. **成本/预算的维度升级（token 记账）**。DSH 的 `TokenMeter` 提供精细化 token 记账但暴露"usage 未进会话账单"缺口（`packages/llm/token-meter/src/index.ts`；`packages/web/web-search-deepseek/src/provider.ts` 的搜索不走 ctx.llm）。MVP 的 `CostTracker` 已按 token/费用记账并落盘 `cost.jsonl`，但 `remaining_budget` 是粗粒度轮数递减/减半（mvp.md 第 8 条缺口），无 run-away/熔断。**价值**：把预算从"轮数"升级为"token/时间成本上限 + 熔断"，并复用 DSH 教训——**所有 token 消耗（含搜索/内部调用）必须进同一记账，否则会出现"隐性免费 token"**。**成本**：中——需在 `CostTracker.record` 处把所有消耗点统一拦接，并给 `_schedule`/`_execute_packet` 加预算硬断言。

5. **（补充）显式启动/生命周期与分层边界（boot/装配）**。DSH 从 `apps/cli/src/bin.ts` → `profile-boot.ts` → `packages/boot/app-boot/src/index.ts` 的 `boot()` 有一整条可测试的启动链路 + 进程关停控制器（`apps/cli/src/process-shutdown.ts`，`PROCESS_SHUTDOWN_TIMEOUT_MS`）。MVP 是单体 main 直跑、无分层模块边界与关停控制器。**价值**：为 MVP 拆出"装配层"与"执行引擎"边界，便于单测 `boot()` 等价入口与优雅关停。**成本**：改造大（需重构单文件为多模块），适合作为路线图后期项，非近期必做。

---

> 附：本报告全部源码路径证据来自 findings 目录下四份文件（arch-layers.md / startup.md / subsystems.md / mvp.md），未引入 findings 之外的新断言；两文件间表述差异已在 1.1 节如实标注，未擅自二选一。
