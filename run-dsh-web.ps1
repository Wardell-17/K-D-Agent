# 启动双模型 Agent Web 版（路径自适应：脚本所在目录即项目根，公司/家里通用）
$env:DEEPSEEK_API_KEY=[Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','User')
$env:KIMI_API_KEY=[Environment]::GetEnvironmentVariable('KIMI_API_KEY','User')

# 兼容 .env 中可能使用的 MOONSHOT_API_KEY 变量名
if (-not $env:KIMI_API_KEY -and $env:MOONSHOT_API_KEY) {
    $env:KIMI_API_KEY = $env:MOONSHOT_API_KEY
}

$ROOT = $PSScriptRoot
$env:DSH_HOME = Join-Path $ROOT 'dsh-home'
Set-Location $ROOT

# dsh 版本（仅 npx 兜底用；项目内 npm-global 有本地安装时优先用本地）。
# 升级协议（README 6.1）：升级后跑 compare/smoke_dsh.py 过闸，全绿才放行。
$DSH_VERSION = '0.1.1-rc.2'

# 优先用项目内已装的 dsh（离线也能跑）；没有则 npx 拉指定版本
$localDsh = Join-Path $ROOT 'npm-global\dsh.cmd'
if (Test-Path $localDsh) {
    $dshExe = $localDsh; $dshArgs = @()
} else {
    $dshExe = 'npx'; $dshArgs = @('-y', "@deepseek-ai/dsh@$DSH_VERSION")
}

# 后台监听端口，服务起来后自动打开浏览器
Start-Job -ScriptBlock {
    $ok = $false
    for ($i = 0; $i -lt 120; $i++) {
        try {
            $c = New-Object System.Net.Sockets.TcpClient
            $c.Connect('127.0.0.1', 3080); $c.Close(); $ok = $true; break
        } catch { Start-Sleep -Milliseconds 500 }
    }
    if ($ok) { Start-Process 'http://127.0.0.1:3080' }
} | Out-Null

& $dshExe @dshArgs web --patch (Join-Path $ROOT 'harness-patches\kimi-provider.yml') 2>&1
