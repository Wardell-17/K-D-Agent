$env:DEEPSEEK_API_KEY=[Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','User')
Write-Output ('key_len=' + $env:DEEPSEEK_API_KEY.Length)
Set-Location D:\agent-project
& D:\agent-project\npm-global\dsh.cmd --version 2>&1 | Select-Object -First 3
