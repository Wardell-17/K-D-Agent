$env:DEEPSEEK_API_KEY=[Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','User')
$env:KIMI_API_KEY=[Environment]::GetEnvironmentVariable('KIMI_API_KEY','User')
$env:DSH_HOME='D:\agent-project\dsh-home'
Set-Location D:\agent-project
& D:\agent-project\npm-global\dsh.cmd --help 2>&1 | Select-Object -First 40
