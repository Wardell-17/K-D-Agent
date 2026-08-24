# K-D 总控派发器：从注册表注入 API keys，启动 MVP 编排器
# 用法（由 DSH 主会话调用）：
#   pwsh -File kd_dispatch.ps1 -CardsDir "D:\agent-project\architect-engineer\runs\<ts>\tasks"
#   可加 -Sync 强制同步执行（调试/沙盒环境拦截后台进程时用）
# 行为：默认后台无窗口启动、立即返回，stdout 重定向到 dsh-home\dispatch-logs\<ts>.log
# 日志首行的 "[run] 目录: ..." 即 run 目录；轮询 <run>\report.json 存在即完成。
#
# 已知环境约束（实验 029 实测）：
#   1. 某些执行器（DSH 沙盒）会静默拦截 Start-Process 的隐藏子进程——
#      本脚本启动后 3 秒探活，发现进程已死/未拉起则自动降级为同步直跑。
#   2. 子进程必须带 PYTHONUTF8=1，否则 orchestrator 在 GBK 控制台打印
#      "✗" 等字符时直接崩溃（orchestrator 内部已做 reconfigure 双保险）。
param(
    [Parameter(Mandatory=$true)][string]$CardsDir,
    [switch]$Sync
)

$ErrorActionPreference = "Stop"
$ae = "D:\agent-project\architect-engineer"
$logDir = "D:\agent-project\dsh-home\dispatch-logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

# 从用户注册表读 keys（setx 的存放处；DSH 服务进程环境可能没有）
$reg = "HKCU:\Environment"
$env:KIMI_API_KEY     = (Get-ItemProperty $reg -Name KIMI_API_KEY     -ErrorAction SilentlyContinue).KIMI_API_KEY
$env:DEEPSEEK_API_KEY = (Get-ItemProperty $reg -Name DEEPSEEK_API_KEY -ErrorAction SilentlyContinue).DEEPSEEK_API_KEY
$env:TAVILY_API_KEY   = (Get-ItemProperty $reg -Name TAVILY_API_KEY   -ErrorAction SilentlyContinue).TAVILY_API_KEY
if (-not $env:KIMI_API_KEY -or -not $env:DEEPSEEK_API_KEY) {
    Write-Output "ERROR: 注册表缺 KIMI_API_KEY 或 DEEPSEEK_API_KEY"; exit 1
}
$env:PYTHONUTF8 = "1"   # 子进程强制 UTF-8，防 GBK 控制台崩溃

$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$log = Join-Path $logDir "$ts.log"
$pyArgs = @("orchestrator.py", "--cards", $CardsDir)

function Invoke-Sync {
    Write-Output "SYNC-RUN log=$log"
    & "C:\Python314\python.exe" @pyArgs *> $log
    Write-Output "DONE exit=$LASTEXITCODE log=$log"
}

if ($Sync) {
    Invoke-Sync
    exit $LASTEXITCODE
}

# 无窗口后台启动；退出码与输出进日志
try {
    $p = Start-Process -FilePath "C:\Python314\python.exe" `
         -ArgumentList $pyArgs `
         -WorkingDirectory $ae -WindowStyle Hidden `
         -RedirectStandardOutput $log -RedirectStandardError "$log.err" `
         -PassThru
} catch {
    Write-Output "WARN: Start-Process 被拦截（$($_.Exception.Message)），降级为同步执行"
    Invoke-Sync
    exit $LASTEXITCODE
}

# 探活：3 秒后进程已退出且日志为空 → 视为被沙盒静默拦截，降级同步
Start-Sleep -Seconds 3
$alive = Get-Process -Id $p.Id -ErrorAction SilentlyContinue
$logSize = (Get-Item $log -ErrorAction SilentlyContinue).Length
if (-not $alive -and (-not $logSize)) {
    Write-Output "WARN: 后台进程疑似被沙盒静默拦截（pid=$($p.Id) 已死且日志为空），降级为同步执行"
    Invoke-Sync
    exit $LASTEXITCODE
}

Write-Output "DISPATCHED pid=$($p.Id) log=$log"
Write-Output "下一步：读 $log 首行获取 [run] 目录，然后轮询 <run>\report.json"
