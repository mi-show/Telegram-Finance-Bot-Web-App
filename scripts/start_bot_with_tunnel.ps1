Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$envFile = Join-Path $repoRoot '.env'
$tunnelOutLog = Join-Path $repoRoot 'data\tunnel.out.log'
$tunnelErrLog = Join-Path $repoRoot 'data\tunnel.err.log'

function Test-Url {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url,
        [int]$TimeoutSec = 5
    )

    try {
        $response = Invoke-WebRequest -Uri $Url -TimeoutSec $TimeoutSec -UseBasicParsing
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 400
    }
    catch {
        return $false
    }
}

function Wait-LocalWeb {
    param([int]$TimeoutSec = 90)

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-Url -Url 'http://localhost:8000/api/webapp/health' -TimeoutSec 5) {
            return $true
        }
        Start-Sleep -Seconds 2
    }

    return $false
}

function Wait-UrlHealthy {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url,
        [int]$TimeoutSec = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-Url -Url $Url -TimeoutSec 7) {
            return $true
        }
        Start-Sleep -Seconds 2
    }

    return $false
}

function Get-EnvValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Key
    )

    if (-not (Test-Path $Path)) {
        return $null
    }

    $pattern = '^' + [Regex]::Escape($Key) + '=(.*)$'
    foreach ($line in Get-Content $Path) {
        if ($line -match $pattern) {
            return $matches[1]
        }
    }

    return $null
}

function Set-EnvValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Key,
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    $lines = @()
    if (Test-Path $Path) {
        $lines = Get-Content $Path
    }

    $pattern = '^' + [Regex]::Escape($Key) + '='
    $updated = $false

    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match $pattern) {
            $lines[$i] = "$Key=$Value"
            $updated = $true
            break
        }
    }

    if (-not $updated) {
        $lines += "$Key=$Value"
    }

    Set-Content -Path $Path -Value $lines -Encoding UTF8
}

function Get-KnownTelegramMenuChatIds {
    param(
        [Parameter(Mandatory = $true)]
        [string]$EnvPath,
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    $candidateIds = New-Object System.Collections.Generic.List[string]

    $singleChatId = Get-EnvValue -Path $EnvPath -Key 'TELEGRAM_MENU_CHAT_ID'
    if (-not [string]::IsNullOrWhiteSpace($singleChatId)) {
        $candidateIds.Add($singleChatId.Trim())
    }

    $listChatIds = Get-EnvValue -Path $EnvPath -Key 'TELEGRAM_MENU_CHAT_IDS'
    if (-not [string]::IsNullOrWhiteSpace($listChatIds)) {
        $listChatIds -split '[,;\s]+' |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            ForEach-Object { $candidateIds.Add($_.Trim()) }
    }

    $dbUser = Get-EnvValue -Path $EnvPath -Key 'POSTGRES_USER'
    $dbName = Get-EnvValue -Path $EnvPath -Key 'POSTGRES_DB'
    if (-not [string]::IsNullOrWhiteSpace($dbUser) -and -not [string]::IsNullOrWhiteSpace($dbName)) {
        try {
            Push-Location $RepoRoot
            try {
                $dbChatIds = docker compose exec -T db psql -U $dbUser -d $dbName -At -c "SELECT DISTINCT telegram_id FROM users WHERE telegram_id IS NOT NULL" 2>$null
            }
            finally {
                Pop-Location
            }

            foreach ($dbId in @($dbChatIds)) {
                if (-not [string]::IsNullOrWhiteSpace($dbId)) {
                    $candidateIds.Add($dbId.Trim())
                }
            }
        }
        catch {
            Write-Warning "Could not load telegram_id list from DB: $($_.Exception.Message)"
        }
    }

    $normalized = New-Object System.Collections.Generic.List[string]
    foreach ($id in $candidateIds) {
        $trimmed = $id.Trim()
        if ($trimmed -match '^\d+$' -and -not $normalized.Contains($trimmed)) {
            $normalized.Add($trimmed)
        }
    }

    return @($normalized)
}

function Get-RunningTunnelProcesses {
    return @(Get-CimInstance Win32_Process |
        Where-Object {
            $_.Name -eq 'ssh.exe' -and
            $_.CommandLine -match 'localhost\.run' -and
            $_.CommandLine -match '-R\s+80:localhost:8000'
        })
}

function Stop-RunningTunnel {
    $procs = Get-RunningTunnelProcesses
    foreach ($proc in $procs) {
        Stop-Process -Id $proc.ProcessId -Force
    }
}

function Get-TunnelBaseUrlFromLog {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PrimaryLogPath,
        [Parameter(Mandatory = $true)]
        [string]$SecondaryLogPath,
        [int]$TimeoutSec = 45
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    $tunnelLineRegex = 'tunneled with tls termination,\s*(https://[a-zA-Z0-9.-]+)'

    while ((Get-Date) -lt $deadline) {
        $primaryContent = ''
        $secondaryContent = ''

        if (Test-Path $PrimaryLogPath) {
            $primaryContent = Get-Content -Path $PrimaryLogPath -Raw
        }
        if (Test-Path $SecondaryLogPath) {
            $secondaryContent = Get-Content -Path $SecondaryLogPath -Raw
        }

        $combinedContent = "$primaryContent`n$secondaryContent"
        if ($combinedContent) {
            $lineMatches = [Regex]::Matches($combinedContent, $tunnelLineRegex)
            if ($lineMatches.Count -gt 0) {
                return $lineMatches[$lineMatches.Count - 1].Groups[1].Value.TrimEnd('/')
            }

            if ($combinedContent -match '(?im)^Permission denied(?! error check)|(?im)^channel .*open failed|(?im)^ssh: Could not resolve hostname|(?im)Connection timed out|(?im)administratively prohibited|(?im)^kex_exchange_identification:') {
                throw "Tunnel failed to start. Check $PrimaryLogPath and $SecondaryLogPath"
            }
        }
        Start-Sleep -Seconds 1
    }

    throw "Timed out waiting for tunnel URL in $PrimaryLogPath and $SecondaryLogPath"
}

function Update-TelegramMenuButton {
    param(
        [Parameter(Mandatory = $true)]
        [string]$BotToken,
        [Parameter(Mandatory = $true)]
        [string]$WebAppUrl,
        [string]$ButtonText = 'Finance Web App',
        [string[]]$MenuChatIds = @()
    )

    if ([string]::IsNullOrWhiteSpace($BotToken)) {
        Write-Warning 'BOT_TOKEN is empty. Skipping Telegram menu button update.'
        return $false
    }

    if ([string]::IsNullOrWhiteSpace($WebAppUrl)) {
        Write-Warning 'WEBAPP_URL is empty. Skipping Telegram menu button update.'
        return $false
    }

    $setApiUrl = "https://api.telegram.org/bot$BotToken/setChatMenuButton"
    $getApiUrl = "https://api.telegram.org/bot$BotToken/getChatMenuButton"

    function Confirm-MenuButtonUrl {
        param(
            [Parameter(Mandatory = $true)]
            [string]$ExpectedUrl,
            [string]$ChatId = '',
            [int]$Attempts = 6,
            [int]$DelaySec = 2
        )

        for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
            try {
                $uri = $getApiUrl
                if (-not [string]::IsNullOrWhiteSpace($ChatId)) {
                    $uri = "${getApiUrl}?chat_id=$ChatId"
                }

                $current = Invoke-RestMethod -Method Get -Uri $uri -TimeoutSec 20
                $currentUrl = $current.result.web_app.url
                if ($currentUrl -eq $ExpectedUrl) {
                    return $true
                }
            }
            catch {
                # Retry on transient Telegram API or network failures.
            }

            if ($attempt -lt $Attempts) {
                Start-Sleep -Seconds $DelaySec
            }
        }

        return $false
    }

    $menuButton = @{
        type = 'web_app'
        text = $ButtonText
        web_app = @{
            url = $WebAppUrl
        }
    }

    $updated = $false

    $defaultPayload = @{ menu_button = $menuButton } | ConvertTo-Json -Depth 8

    try {
        $setDefault = Invoke-RestMethod -Method Post -Uri $setApiUrl -ContentType 'application/json' -Body $defaultPayload -TimeoutSec 20
        if ($setDefault.ok -ne $true) {
            Write-Warning "Telegram API returned not-ok while setting default menu button: $($setDefault.description)"
        }

        if (Confirm-MenuButtonUrl -ExpectedUrl $WebAppUrl) {
            Write-Host "Telegram default menu button updated: $WebAppUrl"
            $updated = $true
        }
        else {
            $defaultCurrent = Invoke-RestMethod -Method Get -Uri $getApiUrl -TimeoutSec 20
            $defaultUrl = $defaultCurrent.result.web_app.url
            Write-Warning "Telegram default menu button is still: $defaultUrl"
        }

        foreach ($chatId in @($MenuChatIds)) {
            if ([string]::IsNullOrWhiteSpace($chatId)) {
                continue
            }

            $chatPayload = @{
                chat_id = [int64]$chatId
                menu_button = $menuButton
            } | ConvertTo-Json -Depth 8

            $setChat = Invoke-RestMethod -Method Post -Uri $setApiUrl -ContentType 'application/json' -Body $chatPayload -TimeoutSec 20
            if ($setChat.ok -eq $true) {
                if (Confirm-MenuButtonUrl -ExpectedUrl $WebAppUrl -ChatId $chatId) {
                    Write-Host "Telegram chat menu button updated for ${chatId}: $WebAppUrl"
                    $updated = $true
                }
                else {
                    $chatCurrent = Invoke-RestMethod -Method Get -Uri ("${getApiUrl}?chat_id=$chatId") -TimeoutSec 20
                    $chatUrl = $chatCurrent.result.web_app.url
                    Write-Warning "Telegram chat menu button for $chatId is still: $chatUrl"
                }
            }
            else {
                Write-Warning "Telegram API returned not-ok while setting chat menu button for ${chatId}: $($setChat.description)"
            }
        }

        return $updated
    }
    catch {
        Write-Warning "Failed to update Telegram menu button automatically: $($_.Exception.Message)"
        return $false
    }
}

Write-Host 'Starting docker services: db + finance-web...'
Push-Location $repoRoot
try {
    docker compose up -d db finance-web | Out-Host

    if (-not (Wait-LocalWeb -TimeoutSec 90)) {
        throw 'Local Web App did not become healthy on http://localhost:8000/api/webapp/health'
    }

    New-Item -ItemType Directory -Path (Split-Path -Parent $tunnelOutLog) -Force | Out-Null

    $existingUrl = Get-EnvValue -Path $envFile -Key 'WEBAPP_URL'
    $canReuseExisting = $false

    if ($existingUrl) {
        $healthUrl = ($existingUrl.TrimEnd('/')) -replace '/webapp$', ''
        $healthUrl = "$healthUrl/api/webapp/health"
        $runningTunnels = @(Get-RunningTunnelProcesses)
        if ($runningTunnels.Count -gt 0 -and (Test-Url -Url $healthUrl -TimeoutSec 7)) {
            $canReuseExisting = $true
        }
    }

    if (-not $canReuseExisting) {
        Stop-RunningTunnel
        if (Test-Path $tunnelOutLog) {
            Remove-Item $tunnelOutLog -Force
        }
        if (Test-Path $tunnelErrLog) {
            Remove-Item $tunnelErrLog -Force
        }

        Write-Host 'Starting localhost.run tunnel...'
        $sshArgs = @(
            '-o', 'StrictHostKeyChecking=no',
            '-o', 'ServerAliveInterval=60',
            '-R', '80:localhost:8000',
            'nokey@localhost.run'
        )

        Start-Process -FilePath 'ssh.exe' -ArgumentList $sshArgs -RedirectStandardOutput $tunnelOutLog -RedirectStandardError $tunnelErrLog -WindowStyle Hidden | Out-Null

        $baseUrl = Get-TunnelBaseUrlFromLog -PrimaryLogPath $tunnelOutLog -SecondaryLogPath $tunnelErrLog -TimeoutSec 60
        $webAppUrl = "$baseUrl/webapp"
        $useFallbackUrl = $false

        $tunnelHealthUrl = "$baseUrl/api/webapp/health"
        if (-not (Wait-UrlHealthy -Url $tunnelHealthUrl -TimeoutSec 90)) {
            Write-Warning "Tunnel URL is not reachable yet: $baseUrl"
            Write-Warning 'Last tunnel stdout lines:'
            if (Test-Path $tunnelOutLog) { Get-Content -Path $tunnelOutLog -Tail 20 | ForEach-Object { Write-Warning $_ } }
            Write-Warning 'Last tunnel stderr lines:'
            if (Test-Path $tunnelErrLog) { Get-Content -Path $tunnelErrLog -Tail 20 | ForEach-Object { Write-Warning $_ } }

            Write-Host 'Retrying tunnel startup...'
            Stop-RunningTunnel
            Start-Process -FilePath 'ssh.exe' -ArgumentList $sshArgs -RedirectStandardOutput $tunnelOutLog -RedirectStandardError $tunnelErrLog -WindowStyle Hidden | Out-Null

            $baseUrl = Get-TunnelBaseUrlFromLog -PrimaryLogPath $tunnelOutLog -SecondaryLogPath $tunnelErrLog -TimeoutSec 60
            $webAppUrl = "$baseUrl/webapp"
            $tunnelHealthUrl = "$baseUrl/api/webapp/health"

            if (-not (Wait-UrlHealthy -Url $tunnelHealthUrl -TimeoutSec 90)) {
                Write-Warning "Tunnel URL is still not reachable after retry: $baseUrl"
                if ($existingUrl) {
                    $healthUrl = ($existingUrl.TrimEnd('/')) -replace '/webapp$', ''
                    $healthUrl = "$healthUrl/api/webapp/health"
                    if (Test-Url -Url $healthUrl -TimeoutSec 7) {
                        Write-Warning "Reusing existing WEBAPP_URL from .env: $existingUrl"
                        $webAppUrl = $existingUrl
                        $useFallbackUrl = $true
                    }
                }

                if (-not $useFallbackUrl -and (Test-Url -Url 'http://localhost:8000/api/webapp/health' -TimeoutSec 7)) {
                    $webAppUrl = 'http://localhost:8000/webapp'
                    Write-Warning "Falling back to local WEBAPP_URL: $webAppUrl"
                    $useFallbackUrl = $true
                }

                if (-not $useFallbackUrl) {
                    throw "Tunnel URL is not reachable yet: $baseUrl"
                }
            }
        }

        Set-EnvValue -Path $envFile -Key 'WEBAPP_URL' -Value $webAppUrl
        Write-Host "WEBAPP_URL updated: $webAppUrl"
    } else {
        $webAppUrl = $existingUrl
        Write-Host "Reusing current WEBAPP_URL: $existingUrl"
    }

    $botToken = Get-EnvValue -Path $envFile -Key 'BOT_TOKEN'
    $menuChatIds = Get-KnownTelegramMenuChatIds -EnvPath $envFile -RepoRoot $repoRoot
    if ($webAppUrl -like 'http://localhost*') {
        Write-Warning 'Local WEBAPP_URL is configured; skipping Telegram menu button update.'
    }
    else {
        [void](Update-TelegramMenuButton -BotToken $botToken -WebAppUrl $webAppUrl -MenuChatIds $menuChatIds)
    }

    Write-Host 'Starting finance-bot with fresh WEBAPP_URL...'
    docker compose up -d finance-bot | Out-Host

    $finalWebAppUrl = Get-EnvValue -Path $envFile -Key 'WEBAPP_URL'
    Write-Host "Ready. Web App URL: $finalWebAppUrl"
}
finally {
    Pop-Location
}
