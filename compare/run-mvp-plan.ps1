$env:DEEPSEEK_API_KEY=[Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','User')
$env:KIMI_API_KEY=[Environment]::GetEnvironmentVariable('KIMI_API_KEY','User')
Set-Location 'D:\agent-project\architect-engineer'
$task = Get-Content -Raw -Encoding UTF8 'D:\agent-project\compare\task.txt'
python 'D:\agent-project\architect-engineer\orchestrator.py' --plan-only $task 2>&1
