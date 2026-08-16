$env:DEEPSEEK_API_KEY=[Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','User')
$env:KIMI_API_KEY=[Environment]::GetEnvironmentVariable('KIMI_API_KEY','User')

# 兼容 .env 中可能使用的 MOONSHOT_API_KEY 变量名
if (-not $env:KIMI_API_KEY -and $env:MOONSHOT_API_KEY) {
    $env:KIMI_API_KEY = $env:MOONSHOT_API_KEY
}

$env:DSH_HOME='E:\DSH\K-D-Agent\dsh-home'
Set-Location 'E:\DSH\K-D-Agent'
$DSH_VERSION = '0.1.0-rc.6'
npx -y "@deepseek-ai/dsh@$DSH_VERSION" --profile headless --patch 'E:\DSH\K-D-Agent\harness-patches\kimi-provider.yml' $args[0] 2>&1
