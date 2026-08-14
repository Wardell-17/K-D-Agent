$env:DEEPSEEK_API_KEY=[Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','User')
$env:KIMI_API_KEY=[Environment]::GetEnvironmentVariable('KIMI_API_KEY','User')
$env:DSH_HOME='D:\agent-project\dsh-home'
Set-Location 'D:\agent-project\harness-test2'
$task = Get-Content -Raw -Encoding UTF8 'D:\agent-project\harness-test2\task.txt'
& 'D:\agent-project\npm-global\dsh.cmd' --profile headless --patch 'D:\agent-project\harness-patches\kimi-provider.yml' $task 2>&1
