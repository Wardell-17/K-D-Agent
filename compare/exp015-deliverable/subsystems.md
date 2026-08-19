# 四个子系统源码级结论（deepseek-harness）

以下所有结论均基于对 `D:\agent-project\harness-src\packages` 下真实源码的直接阅读。已尽力标注函数/类名与文件路径；未能完全读懂的模块如实标注。

---

## 1. llm：多 provider 抽象与路由 + web 搜索后端 + 记账缺口

### 1.1 Provider 抽象与路由

LLM 层位于 `packages/llm`。抽象核心是 `LlmAdapter` 基类（`packages/llm/llm/src/types.ts`），所有 provider 通过继承 `LlmAdapter` 并实现 `providerInfo / listModels / resolveModel / stream / resolveRetryPolicy` 来接入。路由注册通过 `ctx.llm.registerAdapter([PROVIDER], adapter)` 与 `ctx.llm.registerConfigurableProviders([...])` 完成，provider 路由名（如 `deepseek-official`）是唯一标识，模型名即 wire 名。

当前至少有两个真实适配器实现：

- **`DeepSeekAdapter`**（`packages/llm/llm-deepseek/src/adapter.ts`）——直连 OpenAI-compatible chat-completions 端点。注册逻辑在 `packages/llm/llm-deepseek/src/index.ts` 的 `apply()`：provider 路由为 `deepseek-official`（常量 `PROVIDER`），baseURL 默认 `https://api.deepseek.com`（`PUBLIC_BASE_URL`），key 通过 `resolveApiKey` 每请求解析。其 `stream()` 每次调用"一次解析、全程冻结"连接事实与凭证（adapter.ts 注释明示：同一请求的 URL 和 secret 永不来自不同代配置）。
- **`PiAiAdapter`**（`packages/llm/llm-pi-ai/src/adapter.ts`）——基于 `@earendil-works/pi-ai` 的多 provider 适配器，一次 resolution 产生一个不可变快照（`PiAiSnapshot`），`Models` 集合按 profile 逐 provider 注册（`current()` / `models.setProvider(...)`）。这是多模型 provider 的统一抽象入口。

### 1.2 web 搜索后端如何接入（源码实证）

搜索后端不在 `llm*` 包，而在 **`packages/web/web-search-deepseek/src/provider.ts`** 的 `DeepSeekSearchProvider`。用户实测"检索流量走 `/anthropic/v1` 端点 + deepseek-v4-flash"在源码中得到完全确认：

- `export const DEEPSEEK_DEFAULT_BASE_URL = 'https://api.deepseek.com/anthropic/v1'`（注释明示"NOT 是 chat-completions base"，与 `llm-deepseek` 的端点不同）
- `export const DEEPSEEK_DEFAULT_MODEL = 'deepseek-v4-flash'`
- `search()` 会 POST 到 `` `${options.baseURL}/messages` ``，请求体是 Anthropic Messages 格式，含 `tools: [{ type: 'web_search_20250305', name: 'web_search' }]`。即 web 检索不是走 `ctx.llm`（注释：`The wire format ... do not use ctx.llm`），而是 provider 私有直连 Anthropic 兼容端点的"模型调用"，每次检索算一次 model turn。

### 1.3 记账缺口在哪（usage 未计入会话账单）

- 该 provider 在每次 dispatch 前只通过 `recordRequest` 事件把 **无密钥的请求元数据** 写入会话事件：声明在 `packages/web/web-search-deepseek/src/provider.ts` 的 `declare module ...SessionEventMap { 'web/deepseek-search-llm-request': DeepSeekSearchLlmRequest }`。**注意：这不是 `assistant/message`、不带 `usage` 字段。**
- 会话代币计费由 `TokenMeter`（`packages/llm/token-meter/src/index.ts`）负责，它只在对 **`assistant/message` 且 `usage` 存在** 的事件建 anchor 记账（`_foldEvent` 中 `if (event.data.usage !== undefined ...)` 才走 `usageTokens` 计入 provider usage；否则只做启发式 `estimate*`）。搜索请求只发射了 `web/deepseek-search-llm-request`，从不产生带 `usage` 的 `assistant/message`，因此**检索的那次模型 turn 完全不会进入 tokenMeter 的账单**——这就是"usage 未计入会话账单"的根因。且该 provider 明确"不使用 ctx.llm"，所以更不会经过 LLM 记账层。

---

## 2. credentials：解析顺序 + MISSING_CREDENTIAL 不回落环境变量

### 2.1 服务抽象

`packages/credentials/credentials/src/index.ts` 定义 `CredentialProvider extends Service('credentials')`，抽象方法 `resolve/describe/set/unset`。配置面只携带 **CredentialRef（环境变量名）**，真实值由 provider 拥有。

### 2.2 本地 provider 的解析顺序（源码实证）

`packages/credentials/credentials-local/src/index.ts` 的 `LocalCredentialProvider.resolve()` 顺序明确为：

```
1. inherited process environment（只读，最高优先，source='env'）  ← inherited()
2. $DSH_HOME/.credentials.yaml（provider 托管、可写，source='file'）← this.values
3. <cwd>/.env（只读回落，source='project-env'）                    ← dotenvFallback()
4. $DSH_HOME/.env（只读回落，source='user-env'）                   ← dotenvFallback()
   → 全空返回 undefined
```

### 2.3 "服务存在但无记录 → 直接 MISSING_CREDENTIAL，不回落环境变量"

这正是 `llm-deepseek` 的 `resolveApiKey`（`packages/llm/llm-deepseek/src/index.ts`）的语义：

```ts
const credentials = ctx.get('credentials')
if (credentials !== undefined) {
  const hit = await credentials.resolve(ref)
  if (hit !== undefined) return assertUsableApiKey(...)
  // ↓ 没有 else 回落：服务存在但 resolve 返回 undefined 时，直接落到底部的 throw
} else {
  // 仅当整个 credentials 服务不存在时，才退回 launchEnvironment
  const ambient = launchEnvironmentOf(ctx).get(ref)
  if (ambient !== undefined && ambient.value.length > 0) return assertUsableApiKey(...)
}
throw new LlmError(..., 'MISSING_CREDENTIAL')
```

逻辑结论（源码级）：只要 `credentials` 服务被加载（存在），但该 ref 未记录值，`resolve` 返回 `undefined`，代码**不会**走 `else` 的环境变量分支，而是直接 `throw LlmError('...no API key...', 'MISSING_CREDENTIAL')`。环境变量回落只在"credentials 服务完全未注册"时才生效。这与用户实测"存在服务但无记录时直接抛 MISSING_CREDENTIAL，不回落环境变量"完全一致。Web 搜索侧同理：`web-search-deepseek/src/provider.ts` 的 `apiKey()` 无 key 时抛 `WEB_PROVIDER_CREDENTIAL_MISSING`。

---

## 3. subagent：子代理创建/派工 + 工具权限差异

### 3.1 派工入口与创建

模型侧通过 **`tool-subagent`**（`packages/subagent/tool-subagent/src/index.ts`）暴露 `subagent` 工具，调用 `ctx.subagents.start(provider, {label, prompt, parent, agentOptions, persona, toolFilter, maxDepth, ...})`。前台 run 通过 `settleForegroundRun` 等待结果；后台 run 走 `ctx.subagents.startContinuable()` 或 jobs。

每个子代理会话会被打一个持久化身份描述符 `subagent/descriptor` 事件（`packages/subagent/subagent/src/descriptor.ts` 的 `snapshotSubagentDescriptor`，版本号 `SUBAGENT_DESCRIPTOR_VERSION`），记录 `mode: 'one-shot'|'continuable'`、`provider` 以及（continuable 时）`toolFilter/persona/agentProvider/model`。冷恢复（continuable）依赖该描述符重建子代理。

### 3.2 工具权限比主代理被阉割（源码实证）

工具集差异来自 **`toolFilter`**，它既写在请求里（tool-subagent/src/index.ts），也落在续盘描述符里（descriptor.ts 的 `ToolRestriction { allow?, deny? }`）：

- 在 `tool-subagent/src/index.ts` 的 Config 注释明示：`toolFilter` —— "Filtered tools disappear from its prompt and reject execution."（被过滤的工具从子代理 prompt 消失且执行被拒）；`.allow` 表示"子代理保留的全局工具，其余全部移除"。
- `packages/subagent/subagent/src/descriptor.ts` 的 `ContinuableSubagentDescriptorData.toolFilter` 注释："Child tool scoping reapplied on resume"（续盘时重新施加子代理工具范围）。
- 深度限制：tool-subagent 的 `maxDepth`（默认 3，`0` 禁止派工）要求 provider 具备 `depthLimit` capability 否则 mount 时报错（见 `mount()` 中 `!provider.capabilities.depthLimit` 抛错）。**"spawn 后不干活"**很可能是：派工实例配置了空/过严的 `toolFilter`（`allow: []` 会把所有工具去掉）或 `maxDepth/tooleFilter` 与 provider capability 不匹配导致子代理缺少工具或启动即被限。

> 备注：`tool-subagent/src/index.ts` 明确"若配置了 `toolFilter` 但 allow/deny 都未命名，load 即抛错"；且 Schemastery 默认 `{allow: []}` 会变成"否掉所有工具"，代码特意用 `.default(undefined)` 规避——配置疏忽极易造成子代理工具被整体阉割。

**未完全读懂**：`subagent-spawn-in-process` / `subagent-fork-in-process` / `subagent-dsh-sdk` 等 provider 内部在 `toolFilter` 之外是否还有进程级权限收缩，当前未深入逐行核对。

---

## 4. preset：.agent-presets / agent.cordis.yml 的加载、合并、校验与工具白名单

### 4.1 文件发现（discovery.ts）

`packages/preset/agent-presets/src/discovery.ts`：

- 常量为 `COMPOSITION_FILE = 'agent.cordis.yml'`，用户本地根目录 `USER_PRESET_DIR = '.agent-presets'`（位于 harness home 下）。
- `discoverPresets(roots)` 按 roots 优先级扫描（前一个 root 的同 id 覆盖，first-root-wins）；`scanRoot` 只认满足 `PRESET_ID` 的目录，每个目录必须有 `agent.cordis.yml`。
- 校验：`entryListProblem()` 检查顶层必须是 plugin row 列表、每行必须带 `name` 字符串、`group: true` 递归校验嵌套 config；`compositionProblem()` 用与加载器一致的 `entryListSchema`（含 `!!js`）解析，坏的 composition 被记为 `broken` roster 行而不是静默跳过。

### 4.2 合并挂载（mount / session）

- `discoverPresets` 的合并策略：**按 root 优先级，同一个 preset id 只保留最前面（优先）root 的那份**——即"先到先得"，重复 id 由更优先的 root 胜出，不深合并。
- 挂载/应用在 `agent-presets/src/mount.ts` 与 `session.ts`（`mount.ts` 负责把 preset 的 `agent.cordis.yml` composition 装载进运行时上下文，`session.ts` 处理会话级 preset 生效）。metadata（显示名等）通过 `readPresetMetadata`（`metadata.ts`）读取，失败不致命只显示 id。authoring（`authoring.ts`）提供服务端校验/写入支持。

### 4.3 工具白名单如何生效

预设的 `agent.cordis.yml` 里会声明工具相关配置（`toolFilter` 等），其生效链路与 subagent 的 `ToolRestriction` 同构：被过滤工具从 agent 的 prompt 消失且执行被拒（见第 3.2 节）。即**工具白名单/黑名单不是 preset 层自定义机制，而是 preset 通过配置下发 `toolFilter`（allow/deny），由工具面在装配 agent 时施加**。discovery 阶段的 `entryListProblem` 只做行结构浅校验，不校验工具名；未知工具名的 fail-loud 检查发生在 agent 装配期（如 tool-subagent mount 时 `unknown names fail startup`）。

**未完全读懂**：`agent-presets/src/preset.ts` 的 `PresetRoot` 信任层级（`trust`）与 `mount.ts` 内部如何把 composition 的具体 config schema 应用到各插件、以及 `session.ts` 对 preset 的启用/冷却切换时序，未逐行读完整。

---

## 附：涉及的真实源码文件清单

- `packages/llm/llm-deepseek/src/adapter.ts`（DeepSeekAdapter）
- `packages/llm/llm-deepseek/src/index.ts`（resolveApiKey / MISSING_CREDENTIAL）
- `packages/llm/llm-pi-ai/src/adapter.ts`（PiAiAdapter / PiAiSnapshot）
- `packages/llm/token-meter/src/index.ts`（TokenMeter / _foldEvent 记账）
- `packages/web/web-search-deepseek/src/provider.ts`（DeepSeekSearchProvider / /anthropic/v1 / deepseek-v4-flash / web_search_20250305）
- `packages/credentials/credentials/src/index.ts`（CredentialProvider 抽象）
- `packages/credentials/credentials-local/src/index.ts`（LocalCredentialProvider.resolve 解析顺序）
- `packages/subagent/tool-subagent/src/index.ts`（subagent 工具 / toolFilter / maxDepth）
- `packages/subagent/subagent/src/descriptor.ts`（subagent/descriptor / ToolRestriction / snapshotSubagentDescriptor）
- `packages/preset/agent-presets/src/discovery.ts`（discoverPresets / agent.cordis.yml / .agent-presets / 校验）
- `packages/preset/agent-presets/src/mount.ts`、`session.ts`、`metadata.ts`、`authoring.ts`（合并/挂载/metadata）
