$env:DEEPSEEK_API_KEY=[Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','User')
$env:KIMI_API_KEY=[Environment]::GetEnvironmentVariable('KIMI_API_KEY','User')
$ROOT='D:\agent-project'
$env:DSH_HOME=Join-Path $ROOT 'dsh-home'
Set-Location $ROOT
Write-Output ('env_deepseek_len=' + $env:DEEPSEEK_API_KEY.Length + ' env_kimi_len=' + $env:KIMI_API_KEY.Length)
& D:\agent-project\npm-global\dsh.cmd --profile headless --patch (Join-Path $ROOT 'harness-patches\kimi-provider.yml') 'reply with just: PONG' 2>&1 | Select-Object -First 15
