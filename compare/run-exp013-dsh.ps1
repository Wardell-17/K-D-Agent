# 实验013 DSH 侧：同一事实清单任务，走 dsh 原生检索（自包含版）
$env:DEEPSEEK_API_KEY=[Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','User')
$env:KIMI_API_KEY=[Environment]::GetEnvironmentVariable('KIMI_API_KEY','User')
$ROOT = 'D:\agent-project'
$env:DSH_HOME = Join-Path $ROOT 'dsh-home'
Set-Location $ROOT
$DSH_VERSION = '0.1.0-rc.6'
$localDsh = Join-Path $ROOT 'npm-global\dsh.cmd'
if (Test-Path $localDsh) { $dshExe = $localDsh; $dshArgs = @() } else { $dshExe = 'npx'; $dshArgs = @('-y', "@deepseek-ai/dsh@$DSH_VERSION") }
$task = (Get-Content -Raw -Encoding UTF8 'D:\agent-project\compare\task.txt').Trim()
& $dshExe @dshArgs --profile headless --patch (Join-Path $ROOT 'harness-patches\kimi-provider.yml') $task 2>&1
