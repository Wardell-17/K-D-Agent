$env:DEEPSEEK_API_KEY=[Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','User')
$env:KIMI_API_KEY=[Environment]::GetEnvironmentVariable('KIMI_API_KEY','User')
$env:DSH_HOME='D:\agent-project\dsh-home'
Set-Location 'D:\agent-project'
& 'D:\agent-project\npm-global\dsh.cmd' --profile headless --patch 'D:\agent-project\harness-patches\kimi-provider.yml' $args[0] 2>&1
