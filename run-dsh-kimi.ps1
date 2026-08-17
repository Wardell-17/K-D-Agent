# headless 单次任务（用法：run-dsh-kimi.ps1 "任务描述"）
$env:DEEPSEEK_API_KEY=[Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','User')
$env:KIMI_API_KEY=[Environment]::GetEnvironmentVariable('KIMI_API_KEY','User')

# 兼容 .env 中可能使用的 MOONSHOT_API_KEY 变量名
if (-not $env:KIMI_API_KEY -and $env:MOONSHOT_API_KEY) {
    $env:KIMI_API_KEY = $env:MOONSHOT_API_KEY
}

$ROOT = $PSScriptRoot
$env:DSH_HOME = Join-Path $ROOT 'dsh-home'
Set-Location $ROOT
$DSH_VERSION = '0.1.0-rc.6'

$localDsh = Join-Path $ROOT 'npm-global\dsh.cmd'
if (Test-Path $localDsh) {
    $dshExe = $localDsh; $dshArgs = @()
} else {
    $dshExe = 'npx'; $dshArgs = @('-y', "@deepseek-ai/dsh@$DSH_VERSION")
}

& $dshExe @dshArgs --profile headless --patch (Join-Path $ROOT 'harness-patches\kimi-provider.yml') $args[0] 2>&1
