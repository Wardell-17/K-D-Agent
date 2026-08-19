$env:DEEPSEEK_API_KEY=[Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','User')
$env:KIMI_API_KEY=[Environment]::GetEnvironmentVariable('KIMI_API_KEY','User')
Set-Location 'D:\agent-project\architect-engineer'
python 'D:\agent-project\architect-engineer\orchestrator.py' --resume 'D:\agent-project\architect-engineer\runs\resume-test' 2>&1
