$env:GEMINI_API_KEY=[Environment]::GetEnvironmentVariable('GEMINI_API_KEY','User')
$key = $env:GEMINI_API_KEY
if (-not $key) { Write-Output 'NO_KEY'; exit 1 }
Write-Output ("KEY_PREFIX: " + $key.Substring(0,6) + "...")
$r = Invoke-RestMethod -Uri "https://generativelanguage.googleapis.com/v1beta/models?pageSize=200&key=$key" -Method Get
$r.models | Where-Object { $_.supportedGenerationMethods -contains 'generateContent' } |
  ForEach-Object { $_.name -replace 'models/','' }
