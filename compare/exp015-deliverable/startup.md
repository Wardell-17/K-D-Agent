# dsh CLI 启动链路追踪

> 本文件基于对 `D:\agent-project\harness-src` 下真实源码的逐层阅读，标注每一跳的
> 文件路径（带扩展名）+ 函数/类名。全部路径统一为**正斜杠**格式。

---

## 0. 入口：`apps/cli/package.json` 的 bin 声明

- 文件：`apps/cli/package.json`
- 证据：`"bin": { "dsh": "lib/bin.js" }`
- 说明：命令名 `dsh` 解析到构建产物 `lib/bin.js`；其源码对应 `apps/cli/src/bin.ts`
  （同一目录布局下 `src/` 与 `lib/` 均位于 `apps/cli/` 之下，见 bin.ts 注释）。

---

## 1. bin 入口分发：`apps/cli/src/bin.ts`

- 文件：`apps/cli/src/bin.ts`
- 关键符号（模块 `@deepseek-ai/dsh/bin`）：
  - `readVersion()`：读取 `../package.json` 的 version。
  - `invocation = parseDshArgs(process.argv.slice(2), readVersion())` —— 进入命令解析。
  - `loadLayeredEnv('dsh')`（来自 `@deepseek-ai/dsh-app-boot`）。
  - `switch (invocation.mode)` 分发三态：
    - `'profile'` → `await import('./profile-boot.ts')` 并调用 `runProfile(...)`；
    - `'plugin'` → `./plugin.ts` 的 `runPlugin`；
    - `'dump-config'` → `./dump-config.ts` 的 `runDumpConfig`。

主链路（boot）走 **`profile`** 分支。

---

## 2. 命令解析：`apps/cli/src/args.ts`

- 文件：`apps/cli/src/args.ts`
- 关键符号：`parseDshArgs(argv, version)`，`class Command`（来自 `commander`）。
- 逻辑：解析启动器自有 flag（`--profile`、`--patch`、`--dump-config`、
  `--dump-default-config`、`web` 别名、`plugin` 子命令），``.passThroughOptions()``
  保证第一个未识别 token 之后全部作为内部参数传给目标 profile 的 app。
- 返回 `DshInvocation`，其中 `mode: 'profile'` 携带 `profile`/`patches`/`args`。

---

## 3. profile 启动器：`apps/cli/src/profile-boot.ts`

- 文件：`apps/cli/src/profile-boot.ts`
- 关键符号：`runProfile(options: RunProfileOptions)`，`composeProfile`，
  `prepareProfile`，`resolveTelemetryPatch`。
- `runProfile` 内按序：
  1. `composeProfile(options.profile, options.patchFiles)`：拼接 patch 层
     （bundle 层 → profile 自身 `cordis.patch.yml` → 全局 home layer →
     `--patch` overlay → telemetry 禁用 patch）。
  2. `createProcessShutdown(...)`（来自 `./process-shutdown.ts`）建立关停控制器。
  3. 注册 `SIGTERM`/`SIGINT` → `interrupt`；`installFailLoud`。
  4. `const ctx = await boot(NAME, rootConfig, … )` —— 进入主加载循环（见第 5 节）。
  5. boot 之后安装 HMR `/watchUserPatches` 保持 live，返回 `{ ctx, shutdown }`。

---

## 4. 进程关停：`apps/cli/src/process-shutdown.ts`

- 文件：`apps/cli/src/process-shutdown.ts`
- 关键符号：`createProcessShutdown(dispose, forceExit, complete, timeoutMs)`，
  常量 `PROCESS_SHUTDOWN_TIMEOUT_MS = 5_000`。
- 协议：`shutdown(code)` 优雅退出（先 dispose 再设 process.exitCode）；
  `interrupt(code)` 在重复信号下强制 `process.exit`（`forceExitOnce`）。这是启动
  链路在生命周期侧的配套，由 `profile-boot.ts` 注入。

---

## 5. 主加载循环：`packages/boot/app-boot/src/index.ts`

- 文件：`packages/boot/app-boot/src/index.ts`
- 关键符号：
  - `export async function boot(binName, absoluteConfigPath, patches?, prepare?, bareModuleBaseUrl?)`：
    - `new Context()`（来自 `@deepseek-ai/cordis`）；
    - `await ctx.plugin(Loader)`（`@deepseek-ai/cordis-plugin-loader`）——挂载 Loader 服务；
    - `await prepare?.(ctx)`（`profile-boot` 在此回调里提供
      `DSH_LAUNCH_ENVIRONMENT_KEY` 与 `provideCmdline`）；
    - `await mountRootInclude(ctx, absoluteConfigPath, patches, bareModuleBaseUrl)` ——
      装载根 `cordis.yml` 并把 patch 层 include 进 plugin 树；
    - `await ctx.get('loader')?.await()` + `assertEntriesActivated(ctx, binName)`——
      等待树 settle 并核验激活项。
  - `loadLayeredEnv(binName)`：装载 `.env` 分层快照（inherit › 项目 › Harness home）。
  - `resolveConfigPath(configPath, snapshotMode)`：`$DSH_SNAPSHOT=replay` 时切换
    到 `cordis.snapshot.yml`。

`boot()` 装载完成后，plugin 树（含 session/host 相关组件）通过 Cordis Loader 激活
回调挂载；`profile-boot.ts` 随后安装 HMR 保持用户 layer 热更新，并把进程生命周期
交给已挂载的插件（或组合内的一闪 runner）。对长驻 surface（如 web）即进入
服务监听/主循环阶段。

---

## 参考：链路总览（每步文件路径）

1. `apps/cli/package.json` — `"bin": {"dsh": "lib/bin.js"}`
2. `apps/cli/src/bin.ts` — `readVersion()` / `parseDshArgs` / `loadLayeredEnv` / switch
3. `apps/cli/src/args.ts` — `parseDshArgs` / `class Command`
4. `apps/cli/src/profile-boot.ts` — `runProfile` / `composeProfile` / `prepareProfile`
5. `apps/cli/src/process-shutdown.ts` — `createProcessShutdown` / `shutdown` / `interrupt`
6. `packages/boot/app-boot/src/index.ts` — `boot` / `loadLayeredEnv` / `mountRootInclude` / `assertEntriesActivated`

（`packages/boot/app-boot/src/profile.ts` 还提供 `loadProfile` / `PROFILE_PATCH_FILENAME`
等 profile 装载原语，供第 3 步使用。）
