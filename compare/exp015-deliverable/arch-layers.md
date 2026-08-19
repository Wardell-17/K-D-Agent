# DSH（DeepSeek Harness）总体架构分层

> 依据：仅以 `D:\agent-project\harness-src` 中实际的 `package.json` 依赖（`dependencies`/`peerDependencies`）与关键 import 为证据，辅以 `packages/README.zh.md` 的目录分组说明（该文档本身也强调「禁止凭目录名臆测」）。所有包名均为 `@deepseek-ai/dsh-*`。

根目录 `pnpm-workspace.yaml` 仅声明聚合形式（`packages/*/*`、`apps/*`、`vendor/*`），未拆解层。分层依据是**依赖方向**：叶子（只依赖 `cordis` + `dsh-invariants`/`dsh-util-*`）为基础设施；被核心/能力层引用、又引用核心服务 seam 的为能力层；只依赖 `cordis` + 运行时不变式、被 app 直接用的为宿主侧；最后 apps/* 把所有东西装配起来。

---

## 第 0 层：基础设施层（叶子，几乎零依赖）

这些包的 `package.json` 只声明 `peerDependencies`/`dependencies` 为 `cordis` + `dsh-invariants`（来自共享 `runtime-diagnostics/invariants`），不含任何 harness 业务 seam，是全仓依赖图的叶子。

| 包 | 证据 |
|---|---|
| `packages/util/launch-environment`（`dsh-launch-environment`） | description: "records which layer supplied each value"；peerDeps 仅 `dsh-invariants` + `cordis` |
| `packages/util/atomic-write`, `brand`, `home-paths`, `native-command`, `output-retention`, `timeout` | 同组：组 README 描述 util 为「组间共享的低层零依赖工具（Branded、路径辅助、超时、留存）」 |
| `packages/storage/storage`（`dsh-storage`） | description: "Storage hub ... named backend registry plus mounted data-form facilities"；peerDeps 仅 `dsh-invariants` + `cordis` |
| `packages/host/webserver`（`dsh-host-webserver`） | description: "knows no harness concepts"；deps 仅 `schemastery`，peerDeps 仅 `cordis`+`dsh-invariants` |

> 注意：`util/*` 与 `storage/*` 都属于"基础设施层"但角色不同——`storage` 是持久化数据平面中枢（见第 3 层），`util` 是低层纯工具。二者共同点是依赖面最薄。

---

## 第 1 层：共享运行时不变式与引导胶水

- `packages/runtime-diagnostics/invariants`（`dsh-invariants`）：几乎每个包的 peerDependency 都包含它，提供运行时不变式契约（见 `packages/AGENTS.md` 的 `verify-package-invariants` 规则）。
- `packages/boot`（`dsh-app-boot`）：共享 app bin 启动粘合层，被 `apps/cli` 直接引用（`dsh-app-boot` 出现在 `apps/cli` dependencies 中）。

证据：`apps/cli/package.json` dependencies 含 `@deepseek-ai/dsh-app-boot`、`@deepseek-ai/dsh-cordis-client-runner`；`dsh-agent` 等所有核心包的 peerDeps 都含 `@deepseek-ai/dsh-invariants` 与 `@deepseek-ai/cordis`。

---

## 第 2 层：核心层 `core/`（产品 API 主干，session/agent/tools）

`packages/core/` 内包构成产品 API 主干，它们**引用能力层的 service seam**（llm、scope、session），并被能力层工具、宿主与应用反向聚合。

| 包 | 证据（peerDependencies/依赖） |
|---|---|
| `core/session`（`@deepseek-ai/dsh-session`） | 基础 session 服务 seam；被 `agent`、`agent-loop`、`workflow`、`subagent`、`session-persistence` 等大量包引用 |
| `core/agent`（`dsh-agent`） | peerDeps：`dsh-llm`、`dsh-session`、`dsh-scope`、`dsh-system-prompt`、`dsh-typert-protocol`、`cordis` → 核心 agent 契约依赖 LLM 能力 seam 与 session |
| `core/agent-loop`（`dsh-agent-loop`） | peerDeps：`dsh-agent`、`dsh-llm`、`dsh-session`、`dsh-session-persistence`、`dsh-settings`、`dsh-system-prompt`、`dsh-tools` |
| `core/tools`、`system-prompt`、`scope`、`agent-tool-presentation`、`agent-default-model` | 同组，组成会话/提示工具/agent 具体循环 |

> 核心层是"主干"：`core/agent` 引用 `llm`（能力）、`session`（数据）；而能力层（第 4 层）又引用 `core/agent`/`core/session`，形成「核心 seam ↔ 能力实现」双向引用，由 `host`/`apps` 负责装配消除循环。

---

## 第 3 层：会话数据平面与持久化 `session/`、`storage/`

这些包依赖 `core/session` 基础 seam + `util` 工具，实现持久化/投影/检索。

| 包 | 证据 |
|---|---|
| `session/session-persistence`（`dsh-session-persistence`） | peerDeps：`dsh-session`、`dsh-brand`（util）、`dsh-timeout`（util）、`dsh-scope` → 持久化 seam |
| `session/session-persistence-jsonl`, `session-persistence-sqlite`, `session-projection*`, `session-title*`, `session-stats`, `session-telemetry*` | 同组，persistence 的具体后端（JSONL/SQLite）、投影、标题、遥测；`session-title-*-llm` 依赖 LLM seam |
| `storage/storage-*`（`storage-domain`、`storage-json`、`storage-sqlite`） | `storage/storage` 为中枢（仅依赖 invariants+cordis）；具体后端 extension |
| `session-query/`、`context/`、`compaction/` | 会话关联半侧：检索、模型可见上下文、压缩策略 |

---

## 第 4 层：能力层（capability layers：llm / credentials / subagent / fs / workflow / …）

这一层最常见：**抽象 seam**（只依赖 `core` + `util`）与**具体 provider/consumer**（引用更多 seam）。它们实现"工具/技能/执行"式能力，供核心层消费、被 `apps/cli` 装配。

| 能力 | 包（证据） |
|---|---|
| `llm/` | `llm/llm`（`dsh-llm`）description "Provider-neutral LLM service interface"；peerDeps：`dsh-attachment`、`dsh-brand`、`dsh-timeout`（util）；`llm-deepseek`、`llm-pi-ai`、`llm-retry`、`token-meter` 为 provider/装饰 |
| `credentials/` | `credentials/credentials`（`dsh-credentials`）description "Abstraction credential seam"；peerDeps 仅 `dsh-brand`；`credentials-local` 为 provider（settings 载入） |
| `subagent/` | `subagent/subagent`（`dsh-subagent`）description "Abstract subagent seam ... named-provider registry"；peerDeps 大量引用 `dsh-agent`、`dsh-llm`、`dsh-session`、`dsh-session-persistence`、`dsh-jobs`、`dsh-sandbox`、`dsh-tools`、`dsh-user-approval`；`subagent-acp/claude-code/codex/dsh-sdk` 为具体子代理 provider，`tool-subagent*` 为模型工具 |
| `fs/` | `fs/fs`（`dsh-fs`）description "Abstract filesystem capability seam"；peerDeps：`dsh-brand`、`dsh-llm`、`dsh-sandbox`；`fs-local`、`fs-sandbox` 为 provider，`tool-fs*`、`tool-str-replace-editor` 为模型工具 |
| `workflow/` | `workflow/workflow`（`dsh-workflow`）description "Workflow capability seam: ctx.workflowEngine"；peerDeps：`dsh-agent`、`dsh-llm`、`dsh-session`、`dsh-brand`；`workflow-worker-thread` 为引擎实现，`tool-workflow`、`tool-ralph` 为模型工具 |
| 其余能力组 | `shell/`（bash 执行）、`terminal/`（PTY）、`code-runtime/`、`sandbox/`、`lsp/`、`skill/`、`web/`、`jobs/`、`goal/`、`plan/`、`todo/`、`guard/`、`interaction/`（审批）、`attachment/`、`spill/`、`extensions/`、`hooks/`、`mcp/`、`acp/`、`sdk/`、`schedule/`、`feedback/`、`identity/` 等 |

> 能力层公共特征：每个能力 = **seam（Service Definition，`dsh-<cap>`）** + **provider（`<cap>-local`/`<cap>-<backend>`）** + **consumer/模型工具（`tool-<cap>`）**。例如 `fs`: `fs`(seam)→`fs-local`(provider)→`tool-fs`(tool)；`llm` 同理；`subagent` 同理。这一"capability seam"模式在 `packages/AGENTS.md`（`2026-06-13-capability-seams.md`）有明确约束：扩展插件依赖 Service Definition、绝不依赖具体 provider/consumer。

---

## 第 5 层：Web GUI 宿主侧 `host/` 与客户端 `client/`、`api/`、`typert/`

- `host/`（web GUI 宿主半侧）：如 `host-webserver`「knows no harness concepts」（API 网关 + HTTP 路由服务器）；`host/apiproxy`、`host/frontend-static`、`host/directory-picker*`、`host/plugin-inventory`。宿主侧是"轻"的，只做路由/装配，不内嵌业务。
- `client/`（web GUI 浏览器半侧）：shell、协议层、对象服务、slot、`ui-*` 插件。
- `api/`（Remote BFF 装配 + Typert RPC 网关）、`typert/`（类型图生成/运行时注册表）。

证据：`apps/web/package.json` dependencies 仅 `dsh-client-web` + react/react-dom，devDeps 引 `dsh-client-web-react`、`dsh-client-ui-primitives`、`dsh-host-*`、`dsh-cmdline`、`dsh-pwsh-local` → web 前端建立在 client 库之上、经 host 静态服务。
`apps/cli` devDependencies 引 `dsh-host-frontend-static`、`dsh-host-apiproxy`、`dsh-host-webserver`（web UI 别名走 host 装配）。

---

## 第 6 层：入口/装配层 `apps/`（cli、web）

| 入口 | 包名 | 证据 |
|---|---|---|
| `apps/cli` | `@deepseek-ai/dsh`（提供 `dsh` bin） | dependencies 几乎横跨所有层：`dsh-app-boot`(boot)、`dsh-agent-tool-presentation`(核心)、`dsh-session-projection`(session)、`dsh-skill`/`dsh-jobs-local`/`dsh-workflow-worker-thread`(能力)、`dsh-tool-*`(能力工具几十个)、`dsh-web-app`、`dsh-goal`、`dsh-plan-mode` 等 → 全量装配点 |
| `apps/web` | `@deepseek-ai/dsh-web-frontend` | "vite build over the dsh-client-web shell library; dist/ served by apps/cli's dsh web" → 浏览器侧装配 |

`apps/*` 是`组合包`（assemble），负责人为集成；它们不定义新能力，只把各 seam+provider+consumer 组装为可运行的 `dsh` CLI 与 web 前端。

---

## 分层总结（沿依赖方向，从底层到入口）

```
[apps/cli]  [apps/web]                         ← 装配层（组合包，触发真实运行）
   │            │ (vite→client-web)
[host/*]  [client/*]  [api/*] [typert/*]       ← Web GUI 宿主/客户端 & RPC 网关
   │            │
[core/*]  agent / agent-loop / session / tools / system-prompt / scope   ← 产品 API 主干
   │   ↑        ↓（core 引用能力 seam，能力也回引 core seam）
[能力层 seam+provider+consumer]                ← llm, credentials, subagent, fs,
workflow, shell, terminal, sandbox, lsp, skill, web, jobs, goal, plan,
todo, guard, interaction, attachment, spill, extensions, hooks, mcp, acp, sdk,
schedule, feedback, identity, compaction, context, session-query, e2b ...
   │
[session数据平面 & storage]                    ← session-persistence*, storage*, 投影, 检索
   │
[util/*] [boot] [runtime-diagnostics/invariants] ← 基础设施层（叶子，零/薄依赖）
   （依赖：cordis + dsh-invariants + schemastery）
```

**核心判定依据（非臆测）：**
1. 「叶子/基础设施层」依据 = `util/*`、`storage/storage`、`host/webserver` 等包 peerDeps/deps 仅 `cordis`+`dsh-invariants`（+`schemastery`）。
2. 「核心层」依据 = `core/agent`/`core/agent-loop` 引用 `dsh-llm`、`dsh-session`、`dsh-scope`；且被 `workflow`/`subagent`/`session` 反向引用。
3. 「能力层」依据 = 每个能力组都有 `seam + provider + tool-consumer` 三元结构（如 `llm`/`credentials`/`subagent`/`fs`/`workflow` 的基于 package.json 的 `-local`/`tool-*` 后缀与 peerDeps 引用关系）。
4. 「装配层」依据 = `apps/cli` dependencies 横跨 boot→core→session→能力工具，`apps/web` 仅依赖 client-react + host 静态。

（数据采集于对 `D:\agent-project\harness-src\packages\**\package.json` 的抽查与 `packages/README.zh.md` 分组表交叉核对。）
