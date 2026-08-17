$key=[Environment]::GetEnvironmentVariable('GEMINI_API_KEY','User')
$q=[System.Text.Encoding]::UTF8.GetString([byte[]](0x32,0x30,0x32,0x36))
$body=(@{contents=@(@{parts=@(@{text='When did China e-bike standard GB 17761-2024 take effect? Give official source URL.'})});tools=@(@{google_search=@{}})}|ConvertTo-Json -Depth 6)
$uri="https://generativelanguage.googleapis.com/v1beta/models/gemini-3.7-flash:generateContent?key=$key"
$r=Invoke-RestMethod -Method Post -ContentType 'application/json' -Uri $uri -Body $body
Write-Output '--- ANSWER ---'
$r.candidates[0].content.parts | ForEach-Object { $_.text }
Write-Output '--- SOURCES ---'
$r.candidates[0].groundingMetadata.groundingChunks | ForEach-Object { "$($_.web.title) | $($_.web.uri)" }
Write-Output '--- USAGE ---'
$r.usageMetadata | ConvertTo-Json -Compress
