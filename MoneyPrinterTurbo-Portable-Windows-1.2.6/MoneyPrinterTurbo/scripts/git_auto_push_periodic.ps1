[CmdletBinding()]
param(
    [int]$IntervalMinutes = 30,
    [string]$MessagePrefix = "Auto periodic commit",
    [switch]$DryRun,
    [switch]$RunImmediately,
    [switch]$Once,
    [int]$MaxRuns = 0,
    [int64]$MaxFileBytes = 50MB,
    [switch]$StopOnFailure
)

$ErrorActionPreference = "Stop"

function Write-Log {
    param([string]$Message)

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Host "[$timestamp] $Message"
}

function Invoke-AutoPush {
    param(
        [string]$ScriptPath,
        [string]$MessagePrefix,
        [switch]$DryRun,
        [int64]$MaxFileBytes
    )

    $message = "$MessagePrefix $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $ScriptPath,
        "-Message",
        $message,
        "-MaxFileBytes",
        $MaxFileBytes
    )

    if ($DryRun) {
        $arguments += "-DryRun"
    }

    Write-Log "Starting git auto push check. DryRun=$DryRun"
    & powershell @arguments 2>&1 | ForEach-Object { Write-Host $_ }
    $exitCode = $LASTEXITCODE

    if ($exitCode -eq 0) {
        Write-Log "Git auto push check finished successfully."
    } else {
        Write-Log "Git auto push check failed with exit code $exitCode."
    }

    return $exitCode
}

if ($IntervalMinutes -lt 1) {
    Write-Error "IntervalMinutes must be at least 1."
    exit 1
}

if ($MaxRuns -lt 0) {
    Write-Error "MaxRuns must be 0 or greater. Use 0 for unlimited runs."
    exit 1
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$autoPushScript = Join-Path $scriptRoot "git_auto_push.ps1"

if (-not (Test-Path -LiteralPath $autoPushScript -PathType Leaf)) {
    Write-Error "Missing git_auto_push.ps1 next to this script."
    exit 1
}

$repoRoot = Resolve-Path (Join-Path $scriptRoot "..")
Set-Location $repoRoot

Write-Log "Repository: $repoRoot"
Write-Log "Interval:   $IntervalMinutes minute(s)"
Write-Log "MaxRuns:    $(if ($MaxRuns -eq 0) { 'unlimited' } else { $MaxRuns })"
Write-Log "DryRun:     $DryRun"

$runCount = 0

if (-not $RunImmediately) {
    $nextRun = (Get-Date).AddMinutes($IntervalMinutes)
    Write-Log "First run scheduled at $($nextRun.ToString('yyyy-MM-dd HH:mm:ss'))."
}

while ($true) {
    if (-not $RunImmediately -or $runCount -gt 0) {
        Start-Sleep -Seconds ($IntervalMinutes * 60)
    }

    $runCount += 1
    $exitCode = Invoke-AutoPush `
        -ScriptPath $autoPushScript `
        -MessagePrefix $MessagePrefix `
        -DryRun:$DryRun `
        -MaxFileBytes $MaxFileBytes

    if ($exitCode -ne 0 -and $StopOnFailure) {
        exit $exitCode
    }

    if ($Once -or ($MaxRuns -gt 0 -and $runCount -ge $MaxRuns)) {
        Write-Log "Finished after $runCount run(s)."
        exit $exitCode
    }

    $nextRun = (Get-Date).AddMinutes($IntervalMinutes)
    Write-Log "Next run scheduled at $($nextRun.ToString('yyyy-MM-dd HH:mm:ss')). Press Ctrl+C to stop."
}
