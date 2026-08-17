$key=[Environment]::GetEnvironmentVariable('GEMINI_API_KEY','User')
$body=(@{contents=@(@{parts=@(@{text='Say OK and nothing else.'})})}|ConvertTo-Json -Depth 6)
$uri="https://generativelanguage.googleapis.com/v1beta/models/gemini-3.7-flash:generateContent?key=$key"
try {
  $r=Invoke-RestMethod -Method Post -ContentType 'application/json' -Uri $uri -Body $body
  Write-Output 'PLAIN_OK'
  $r.candidates[0].content.parts[0].text
  $r.usageMetadata | ConvertTo-Json -Compress
} catch {
  Write-Output ("PLAIN_FAIL: " + $_.Exception.Message)
  if ($_.ErrorDetails) { Write-Output $_.ErrorDetails.Message }
}
