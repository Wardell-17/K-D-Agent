$key=[Environment]::GetEnvironmentVariable('GEMINI_API_KEY','User')
$body=(@{contents=@(@{parts=@(@{text='What is the latest stable Python version? Cite source.'})});tools=@(@{google_search=@{}})}|ConvertTo-Json -Depth 6)
foreach ($m in @('gemini-2.5-flash','gemini-3.7-flash')) {
  $uri="https://generativelanguage.googleapis.com/v1beta/models/$m`:generateContent?key=$key"
  try {
    $r=Invoke-RestMethod -Method Post -ContentType 'application/json' -Uri $uri -Body $body
    Write-Output "== $m : OK =="
    $r.candidates[0].content.parts[0].text.Substring(0,[Math]::Min(300,$r.candidates[0].content.parts[0].text.Length))
    Write-Output ("sources: " + ($r.candidates[0].groundingMetadata.groundingChunks.Count))
  } catch {
    Write-Output "== $m : FAIL =="
    if ($_.ErrorDetails) { Write-Output $_.ErrorDetails.Message } else { Write-Output $_.Exception.Message }
  }
}
