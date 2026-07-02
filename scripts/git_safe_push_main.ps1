[CmdletBinding()]
param(
    [string]$Message = "",
    [string]$BaselineStatusPath = "",
    [string]$RepoRoot = "",
    [string]$RemoteName = "origin",
    [string]$ExpectedBranch = "main",
    [string]$ExpectedRemoteUrl = "https://github.com/yoya9933/autovideos.git",
    [string]$CheckScriptPath = "",
    [int64]$MaxFileBytes = 50MB,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Fail {
    param([string]$Message)

    Write-Error $Message
    exit 1
}

function Invoke-External {
    param(
        [string]$Command,
        [string[]]$Arguments,
        [string]$FailureMessage
    )

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & $Command @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    if ($exitCode -ne 0) {
        Fail "$FailureMessage`n$($output -join "`n")"
    }

    return $output
}

function Invoke-Git {
    param([string[]]$Arguments)

    return Invoke-External -Command "git" -Arguments $Arguments -FailureMessage "git $($Arguments -join ' ') failed."
}

function Normalize-RepoPath {
    param([string]$Path)

    return ($Path -replace "\\", "/").Trim('"')
}

function Get-StatusPaths {
    $lines = Invoke-Git @("status", "--porcelain", "--untracked-files=all")
    $paths = @()

    foreach ($line in $lines) {
        if ([string]::IsNullOrWhiteSpace($line) -or $line.Length -lt 4) {
            continue
        }

        $path = $line.Substring(3).Trim()
        if ($path -match " -> ") {
            $path = ($path -split " -> ")[-1]
        }
        $paths += (Normalize-RepoPath $path)
    }

    return $paths | Sort-Object -Unique
}

function Test-PathMatchesAnyPattern {
    param(
        [string]$Path,
        [string[]]$Patterns
    )

    $normalized = Normalize-RepoPath $Path
    foreach ($pattern in $Patterns) {
        if ($normalized -match $pattern) {
            return $true
        }
    }

    return $false
}

function Assert-SafePaths {
    param(
        [string[]]$Paths,
        [string]$Root,
        [int64]$LimitBytes
    )

    $sensitivePatterns = @(
        '(^|/)config\.toml$',
        '(^|/)config\.local\.toml$',
        '(^|/)\.env(\..*)?$',
        '(^|/)[^/]+\.env$',
        '(^|/)client_secret.*\.json$',
        '(^|/)oauth_helper\.',
        '(^|/)storage(/|$)',
        '(^|/)logs(/|$)',
        '(^|/)MoneyPrinterTurbo-Portable-Windows-1\.2\.6/lib(/|$)',
        '(^|/)MoneyPrinterTurbo-Portable-Windows-1\.2\.6/MoneyPrinterTurbo/storage(/|$)',
        '(^|/)MoneyPrinterTurbo-Portable-Windows-1\.2\.6/MoneyPrinterTurbo/resource/songs(/|$)',
        '(^|/)resource/songs(/|$)',
        '(^|/)\.venv(/|$)',
        '(^|/)venv(/|$)',
        '(^|/)__pycache__(/|$)',
        '/__pycache__/',
        '\.(mp4|mov|mkv|webm|mp3|wav|ttc|7z|zip|log|tmp|bak)$'
    )

    $blocked = @()
    $largeFiles = @()

    foreach ($path in $Paths) {
        if ([string]::IsNullOrWhiteSpace($path)) {
            continue
        }

        $normalizedPath = Normalize-RepoPath $path
        $isAllowedExample = $normalizedPath -match '(^|/)\.env\.example$'

        if (-not $isAllowedExample -and (Test-PathMatchesAnyPattern -Path $normalizedPath -Patterns $sensitivePatterns)) {
            $blocked += $normalizedPath
        }

        $fullPath = Join-Path $Root ($normalizedPath -replace "/", "\")
        if (Test-Path -LiteralPath $fullPath -PathType Leaf) {
            $size = (Get-Item -LiteralPath $fullPath).Length
            if ($size -gt $LimitBytes) {
                $largeFiles += "$normalizedPath ($([math]::Round($size / 1MB, 2)) MB)"
            }
        }
    }

    if ($blocked.Count -gt 0) {
        Fail "Refusing to commit sensitive/generated paths:`n - $($blocked -join "`n - ")"
    }

    if ($largeFiles.Count -gt 0) {
        Fail "Refusing to commit files larger than $([math]::Round($LimitBytes / 1MB, 2)) MB:`n - $($largeFiles -join "`n - ")"
    }
}

function Assert-CleanBaseline {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        Fail "BaselineStatusPath is required. Capture `git status --porcelain` before automated edits and pass that file here."
    }

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Fail "Baseline status file was not found: $Path"
    }

    $baseline = Get-Content -LiteralPath $Path -Raw
    if (-not [string]::IsNullOrWhiteSpace($baseline)) {
        Fail "Baseline status is not clean. Refusing to include changes that existed before automation started.`n$baseline"
    }
}

function Invoke-CheckScript {
    param(
        [string]$ScriptPath,
        [string]$Root,
        [string]$DefaultScriptPath
    )

    if (-not (Test-Path -LiteralPath $ScriptPath -PathType Leaf)) {
        Fail "Check script was not found: $ScriptPath"
    }

    Write-Host "Running maintenance checks..."
    $arguments = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $ScriptPath)
    if ((Resolve-Path $ScriptPath).Path -eq (Resolve-Path $DefaultScriptPath).Path) {
        $arguments += @("-RepoRoot", $Root)
    }

    Invoke-External -Command "powershell" -Arguments $arguments -FailureMessage "Maintenance checks failed." | Out-Null
}

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Join-Path $PSScriptRoot ".."
}

$repoRootPath = (Resolve-Path $RepoRoot).Path
$defaultCheckScript = Join-Path $PSScriptRoot "run_maintenance_checks.ps1"
if ([string]::IsNullOrWhiteSpace($CheckScriptPath)) {
    $CheckScriptPath = $defaultCheckScript
}

Assert-CleanBaseline -Path $BaselineStatusPath

Set-Location $repoRootPath

$actualRepoRoot = (Invoke-Git @("rev-parse", "--show-toplevel") | Select-Object -First 1)
if ((Resolve-Path $actualRepoRoot).Path -ne $repoRootPath) {
    Fail "RepoRoot is not the active Git root. Expected $repoRootPath but git reported $actualRepoRoot."
}

$branch = (Invoke-Git @("branch", "--show-current") | Select-Object -First 1)
if ($branch -ne $ExpectedBranch) {
    Fail "Expected branch '$ExpectedBranch' but current branch is '$branch'."
}

$remoteUrl = (Invoke-Git @("remote", "get-url", $RemoteName) | Select-Object -First 1)
if ($remoteUrl -ne $ExpectedRemoteUrl) {
    Fail "Unexpected $RemoteName remote. Expected '$ExpectedRemoteUrl' but found '$remoteUrl'."
}

Write-Host "Fetching $RemoteName/$ExpectedBranch..."
Invoke-Git @("fetch", "--prune", $RemoteName, $ExpectedBranch) | Out-Null

$localHead = (Invoke-Git @("rev-parse", "HEAD") | Select-Object -First 1)
$remoteHead = (Invoke-Git @("rev-parse", "$RemoteName/$ExpectedBranch") | Select-Object -First 1)
if ($localHead -ne $remoteHead) {
    Fail "Local $ExpectedBranch is not synchronized with $RemoteName/$ExpectedBranch. Refusing to auto-push."
}

$statusPaths = Get-StatusPaths
if ($statusPaths.Count -eq 0) {
    Write-Host "No changes to commit."
    exit 0
}

Assert-SafePaths -Paths $statusPaths -Root $repoRootPath -LimitBytes $MaxFileBytes
Invoke-CheckScript -ScriptPath $CheckScriptPath -Root $repoRootPath -DefaultScriptPath $defaultCheckScript

$statusPaths = Get-StatusPaths
if ($statusPaths.Count -eq 0) {
    Write-Host "No changes to commit after maintenance checks."
    exit 0
}

Assert-SafePaths -Paths $statusPaths -Root $repoRootPath -LimitBytes $MaxFileBytes

if ([string]::IsNullOrWhiteSpace($Message)) {
    $Message = "auto-maintenance: nightly update $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
} elseif ($Message -notmatch '^auto-maintenance: ') {
    $Message = "auto-maintenance: $Message"
}

if ($DryRun) {
    Write-Host "DRY RUN: safety checks passed."
    Write-Host "DRY RUN: would stage $($statusPaths.Count) path(s)."
    Write-Host "DRY RUN: would commit with message: $Message"
    Write-Host "DRY RUN: would push $RemoteName $ExpectedBranch"
    exit 0
}

Invoke-Git @("add", "-A") | Out-Null

$stagedPaths = Invoke-Git @("diff", "--cached", "--name-only")
if ($stagedPaths.Count -eq 0) {
    Write-Host "No staged changes to commit."
    exit 0
}

Assert-SafePaths -Paths $stagedPaths -Root $repoRootPath -LimitBytes $MaxFileBytes

Invoke-Git @("commit", "-m", $Message) | Out-Null
$commitHash = (Invoke-Git @("rev-parse", "HEAD") | Select-Object -First 1)
Invoke-Git @("push", $RemoteName, $ExpectedBranch) | Out-Null

Write-Host "Pushed $ExpectedBranch to $RemoteName successfully."
Write-Host "Commit: $commitHash"
Write-Host "Rollback: git revert $commitHash && git push $RemoteName $ExpectedBranch"
