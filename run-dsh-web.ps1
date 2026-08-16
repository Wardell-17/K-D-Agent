$env:DEEPSEEK_API_KEY=[Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','User')
$env:KIMI_API_KEY=[Environment]::GetEnvironmentVariable('KIMI_API_KEY','User')

# 兼容 .env 中可能使用的 MOONSHOT_API_KEY 变量名
if (-not $env:KIMI_API_KEY -and $env:MOONSHOT_API_KEY) {
    $env:KIMI_API_KEY = $env:MOONSHOT_API_KEY
}

$env:DSH_HOME='E:\DSH\K-D-Agent\dsh-home'
Set-Location 'E:\DSH\K-D-Agent'

# dsh 版本钉死：升级时改这里，验证通过后再提交（流程见 README 第 6.1 节）
$DSH_VERSION = '0.1.0-rc.6'

# 后台监听端口，服务起来后自动打开浏览器
Start-Job -ScriptBlock {
    $ok = $false
    for ($i = 0; $i -lt 120; $i++) {
        try {
            $c = New-Object System.Net.Sockets.TcpClient
            $c.Connect('127.0.0.1', 3080); $c.Close(); $ok = $true; break
        } catch { Start-Sleep -Milliseconds 500 }
    }
    if ($ok) { Start-Process 'http://127.0.0.1:3080' }
} | Out-Null

npx -y "@deepseek-ai/dsh@$DSH_VERSION" web --patch 'E:\DSH\K-D-Agent\harness-patches\kimi-provider.yml' 2>&1
