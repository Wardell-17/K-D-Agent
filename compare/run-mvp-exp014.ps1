param([Parameter(Mandatory=$true)][string]$CardPath)
$env:DEEPSEEK_API_KEY=[Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','User')
$env:KIMI_API_KEY=[Environment]::GetEnvironmentVariable('KIMI_API_KEY','User')
$env:TAVILY_API_KEY=[Environment]::GetEnvironmentVariable('TAVILY_API_KEY','User')
Set-Location 'D:\agent-project\architect-engineer'
python 'D:\agent-project\architect-engineer\orchestrator.py' --card $CardPath 2>&1
