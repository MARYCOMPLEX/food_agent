[CmdletBinding()]
param(
    [switch]$SkipPhoenix,
    [switch]$SkipBuild,
    [switch]$KeepStack,
    [switch]$ResetVolumes,
    [string]$ProjectName = "food-agent-qualification"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ReleaseCompose = Join-Path $Root "docker-compose.release.yml"
$QualificationCompose = Join-Path $Root "docker-compose.qualification.yml"

function Test-Truthy {
    param([AllowNull()][string]$Value)

    return $Value -match "^(?i:true|1|yes|on)$"
}

if ((Test-Truthy $env:COMPOSE_MATRIX_SKIP_PHOENIX) -or
    (Test-Truthy $env:QUALIFICATION_SKIP_PHOENIX)) {
    $SkipPhoenix = $true
}

if (-not [string]::IsNullOrWhiteSpace($env:COMPOSE_MATRIX_PROJECT)) {
    $ProjectName = $env:COMPOSE_MATRIX_PROJECT
}

if (-not (Test-Path -LiteralPath $ReleaseCompose)) {
    throw "Missing release Compose file: $ReleaseCompose"
}
if (-not (Test-Path -LiteralPath $QualificationCompose)) {
    throw "Missing qualification Compose file: $QualificationCompose"
}

$ComposeBase = @(
    "compose",
    "-p",
    $ProjectName,
    "-f",
    $ReleaseCompose,
    "-f",
    $QualificationCompose
)

function ConvertTo-SafeText {
    param([AllowNull()][object]$Value)

    $text = if ($null -eq $Value) { "" } else { [string]$Value }
    # Redact credential-like values before reporting command failures.
    $text = $text -replace "(?im)(OPENAI_API_KEY|[A-Z0-9_]*(?:PASSWORD|TOKEN|SECRET|API[_-]?KEY|AUTHORIZATION)[A-Z0-9_]*)\s*[=:]\s*(\S+)", '$1=<redacted>'
    $text = $text -replace "(?i)sk-[A-Za-z0-9_-]{10,}", "<redacted-key>"
    $text = $text -replace "(?i)([a-z][a-z0-9+.-]*://)([^/\s:@]+):([^@\s]+)@", '$1<redacted>@'
    return $text
}

function Invoke-Compose {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [switch]$ShowFailureOutput
    )

    $command = @($ComposeBase) + @($Arguments)
    $raw = @(& docker @command 2>&1 | ForEach-Object { [string]$_ })
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        $safe = ConvertTo-SafeText ($raw -join [Environment]::NewLine)
        if (-not $ShowFailureOutput) {
            $safe = (($safe -split "`r?`n") | Select-Object -Last 12) -join [Environment]::NewLine
        }
        throw "docker compose $($Arguments -join ' ') failed with exit code $exitCode`n$safe"
    }
    return $raw
}

function Invoke-Docker {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $raw = @(& docker @Arguments 2>&1 | ForEach-Object { [string]$_ })
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        $safe = ConvertTo-SafeText ($raw -join [Environment]::NewLine)
        throw "docker $($Arguments -join ' ') failed with exit code $exitCode`n$safe"
    }
    return $raw
}

function Assert-HttpStatus {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Uri
    )

    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 10 -ErrorAction Stop
        if ([int]$response.StatusCode -ne 200) {
            throw "HTTP status $($response.StatusCode)"
        }
    }
    catch {
        throw "HTTP health check failed for ${Uri}: $($_.Exception.Message)"
    }
    Write-Host "[PASS] HTTP 200 $Uri"
}

function Wait-ContainerExitZero {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Service,
        [int]$TimeoutSeconds = 180
    )

    $name = "$ProjectName-$Service-1"
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $raw = @(& docker inspect --format "{{.State.Status}}|{{.State.ExitCode}}" $name 2>$null)
        if ($LASTEXITCODE -eq 0 -and $raw.Count -gt 0) {
            $state, $exitCode = ([string]$raw[0]).Split("|", 2)
            if ($state -eq "exited") {
                if ([int]$exitCode -eq 0) {
                    Write-Host "[PASS] $Service completed with exit code 0"
                    return
                }
                throw "$Service exited with code $exitCode"
            }
        }
        Start-Sleep -Seconds 2
    }
    throw "$Service did not complete within ${TimeoutSeconds}s"
}

function Wait-ContainerHealthy {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Service,
        [int]$TimeoutSeconds = 180
    )

    $name = "$ProjectName-$Service-1"
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $raw = @(& docker inspect --format "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}" $name 2>$null)
        if ($LASTEXITCODE -eq 0 -and $raw.Count -gt 0) {
            $state, $health = ([string]$raw[0]).Split("|", 2)
            if ($state -eq "running" -and ($health -eq "healthy" -or $health -eq "none")) {
                Write-Host "[PASS] $Service is running ($health)"
                return
            }
        }
        Start-Sleep -Seconds 2
    }
    throw "$Service did not become healthy within ${TimeoutSeconds}s"
}

function Assert-ServiceAbsent {
    param([Parameter(Mandatory = $true)][string]$Service)

    $ids = @(& docker ps -a --filter "label=com.docker.compose.project=$ProjectName" --filter "label=com.docker.compose.service=$Service" -q 2>$null)
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect Compose service $Service"
    }
    if ($ids.Count -ne 0) {
        throw "Service $Service is present while its profile is disabled"
    }
    Write-Host "[PASS] $Service absent with Phoenix profile disabled"
}

function Restart-And-Check {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Service,
        [string]$HealthUri
    )

    Invoke-Compose @("restart", $Service) | Out-Null
    Invoke-Compose @("up", "-d", $Service) | Out-Null
    Wait-ContainerHealthy $Service
    Write-Host "[PASS] restart/recovery $Service"
    if (-not [string]::IsNullOrWhiteSpace($HealthUri)) {
        Assert-HttpStatus $HealthUri
    }
}

function Invoke-QueueSmoke {
    param([Parameter(Mandatory = $true)][string]$Service)

    Invoke-Compose @("run", "--no-deps", "--rm", $Service) | Out-Null
    Write-Host "[PASS] queue smoke $Service"
}

function Test-PhoenixPullFailure {
    param([Parameter(Mandatory = $true)][string]$Message)

    return $Message -match "(?i)(pull|authorization|unauthorized|access denied|tls handshake|manifest|connection reset|network is unreachable|i/o timeout)"
}

$exitCode = 0
$phoenixBlocked = $false
$phoenixStarted = $false
$coreServices = @("postgres", "redis", "temporal", "minio")

try {
    Write-Host "Compose qualification matrix: project=$ProjectName"
    Write-Host "Secrets are not printed; Compose output is captured and redacted."

    $cleanupArgs = @("--profile", "phoenix", "down", "--remove-orphans")
    if ($ResetVolumes) {
        $cleanupArgs += "--volumes"
    }
    Invoke-Compose $cleanupArgs | Out-Null

    Invoke-Compose @("config", "--quiet") | Out-Null
    Write-Host "[PASS] default Compose config"

    if ($SkipPhoenix) {
        Write-Host "[SKIP] Phoenix profile requested by switch/environment"
    }
    else {
        Invoke-Compose @("--profile", "phoenix", "config", "--quiet") | Out-Null
        Write-Host "[PASS] Phoenix Compose config"
    }

    if ($SkipBuild) {
        Write-Host "[SKIP] qualification image build requested by switch"
    }
    else {
        Invoke-Compose @("build", "app") | Out-Null
        Write-Host "[PASS] qualification image build"
    }

    $coreUpArguments = @("up", "-d", "--force-recreate") + $coreServices
    Invoke-Compose $coreUpArguments | Out-Null
    foreach ($service in $coreServices) {
        Wait-ContainerHealthy $service
    }
    Invoke-Compose @("run", "--rm", "migrate") | Out-Null
    Write-Host "[PASS] migration completed after dependency health"
    Invoke-Compose @("up", "-d", "--force-recreate", "app") | Out-Null
    Wait-ContainerHealthy "app"
    Write-Host "[PASS] default profile startup and dependency ordering"
    Invoke-QueueSmoke "research-queue-smoke"
    Invoke-QueueSmoke "refresh-queue-smoke"
    Invoke-QueueSmoke "media-queue-smoke"
    Assert-HttpStatus "http://127.0.0.1:18080/health"
    Assert-HttpStatus "http://127.0.0.1:18080/metrics"
    Assert-ServiceAbsent "phoenix"
    Assert-ServiceAbsent "phoenix-postgres"

    Restart-And-Check "app" "http://127.0.0.1:18080/health"
    Restart-And-Check "postgres"
    Invoke-Compose @("up", "-d", "app") | Out-Null
    Wait-ContainerHealthy "app"
    Assert-HttpStatus "http://127.0.0.1:18080/health"
    Restart-And-Check "redis"
    Restart-And-Check "temporal"
    Invoke-QueueSmoke "research-queue-smoke"
    Write-Host "[PASS] research queue after Temporal restart"

    if (-not $SkipPhoenix) {
        try {
            $phoenixServices = $coreServices + @("phoenix-postgres", "phoenix")
            $phoenixUpArguments = @("--profile", "phoenix", "up", "-d", "--wait", "--wait-timeout", "240") + $phoenixServices
            Invoke-Compose $phoenixUpArguments | Out-Null
            $phoenixStarted = $true
            Write-Host "[PASS] Phoenix profile startup and dependency ordering"
            Assert-HttpStatus "http://127.0.0.1:16080/healthz"
            Restart-And-Check "phoenix-postgres"
            Restart-And-Check "phoenix" "http://127.0.0.1:16080/healthz"
            Write-Host "[INFO] Phoenix service health passed; no OTLP ingestion PASS is claimed."
        }
        catch {
            $message = [string]$_.Exception.Message
            if (Test-PhoenixPullFailure $message) {
                $phoenixBlocked = $true
                Write-Host "[BLOCKED] Phoenix profile could not be pulled or reached: $(ConvertTo-SafeText $message)"
            }
            else {
                throw
            }
        }
    }
}
catch {
    $exitCode = 1
    Write-Host "[FAIL] $(ConvertTo-SafeText $_.Exception.Message)"
}
finally {
    if (-not $KeepStack) {
        try {
            Invoke-Compose @("--profile", "phoenix", "down", "--remove-orphans") | Out-Null
            Write-Host "[PASS] qualification stack cleaned up"
        }
        catch {
            $exitCode = 1
            Write-Host "[FAIL] cleanup: $(ConvertTo-SafeText $_.Exception.Message)"
        }
    }
    else {
        Write-Host "[INFO] stack retained because -KeepStack was specified"
    }
}

if ($phoenixBlocked -and $exitCode -eq 0) {
    Write-Host "[BLOCKED] Matrix completed for business services; Phoenix evidence is unavailable."
    exit 2
}
if ($exitCode -ne 0) {
    exit $exitCode
}

Write-Host "[PASS] Compose qualification matrix completed; Phoenix ingestion was not qualified."
exit 0
