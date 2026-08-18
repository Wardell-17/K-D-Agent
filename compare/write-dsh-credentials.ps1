$d=[Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','User')
$k=[Environment]::GetEnvironmentVariable('KIMI_API_KEY','User')
if (-not $d -or -not $k) { Write-Output 'MISSING ENV'; exit 1 }
$content = "DEEPSEEK_API_KEY: $d`nKIMI_API_KEY: $k`n"
$path = 'D:\agent-project\dsh-home\.credentials.yaml'
[System.IO.File]::WriteAllText($path, $content, [System.Text.UTF8Encoding]::new($false))
Write-Output ('written: ' + $path + ' bytes=' + (Get-Item $path).Length)
