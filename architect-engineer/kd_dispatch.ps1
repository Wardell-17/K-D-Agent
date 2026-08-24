# K-D 总控派发器：从注册表注入 API keys，后台无窗口启动 MVP 编排器
# 用法（由 DSH 主会话调用）：
#   pwsh -File kd_dispatch.ps1 -CardsDir "D:\agent-project\architect-engineer\runs\<ts>\tasks"
# 行为：立即返回（不等待），stdout 重定向到 dsh-home\dispatch-logs\<ts>.log
# 日志首行的 "[run] 目录: ..." 即 run 目录；轮询 <run>\report.json 存在即完成。
param([Parameter(Mandatory=$true)][string]$CardsDir)

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

$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$log = Join-Path $logDir "$ts.log"
# 无窗口后台启动；退出码与输出进日志
$p = Start-Process -FilePath "C:\Python314\python.exe" `
     -ArgumentList @("orchestrator.py", "--cards", $CardsDir) `
     -WorkingDirectory $ae -WindowStyle Hidden `
     -RedirectStandardOutput $log -RedirectStandardError "$log.err" `
     -PassThru
Write-Output "DISPATCHED pid=$($p.Id) log=$log"
Write-Output "下一步：读 $log 首行获取 [run] 目录，然后轮询 <run>\report.json"
