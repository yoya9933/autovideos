[CmdletBinding()]
param(
    [string]$Message = "",
    [switch]$DryRun,
    [int64]$MaxFileBytes = 50MB,
    [switch]$AllowUpstreamOrigin
)

$ErrorActionPreference = "Stop"

function Fail($Message) {
    Write-Error $Message
    exit 1
}

function Invoke-Git {
    param([string[]]$Arguments)

    & git @Arguments
    if ($LASTEXITCODE -ne 0) {
        Fail "git $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

function Get-GitOutput {
    param([string[]]$Arguments)

    $output = & git @Arguments
    if ($LASTEXITCODE -ne 0) {
        Fail "git $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
    return $output
}

function Normalize-RepoPath($Path) {
    return ($Path -replace "\\", "/").Trim('"')
}

function Get-StatusPaths {
    $lines = Get-GitOutput @("status", "--porcelain")
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
    return $paths
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
        [string]$RepoRoot,
        [int64]$MaxFileBytes
    )

    $sensitivePatterns = @(
        '(^|/)config\.toml$',
        '(^|/)\.env(\..*)?$',
        '(^|/)client_secret.*\.json$',
        '(^|/)storage(/|$)',
        '(^|/)\.venv(/|$)',
        '(^|/)venv(/|$)',
        '(^|/)__pycache__(/|$)',
        '\.mp4$',
        '\.log$'
    )

    $blocked = @()
    $largeFiles = @()

    foreach ($path in $Paths) {
        if ([string]::IsNullOrWhiteSpace($path)) {
            continue
        }

        $normalizedPath = Normalize-RepoPath $path
        $isAllowedExample = $normalizedPath -match '(^|/)\.env\.example$'

        if (-not $isAllowedExample -and (Test-PathMatchesAnyPattern -Path $path -Patterns $sensitivePatterns)) {
            $blocked += $path
        }

        $fullPath = Join-Path $RepoRoot $path
        if (Test-Path -LiteralPath $fullPath -PathType Leaf) {
            $size = (Get-Item -LiteralPath $fullPath).Length
            if ($size -gt $MaxFileBytes) {
                $largeFiles += "$path ($([math]::Round($size / 1MB, 2)) MB)"
            }
        }
    }

    if ($blocked.Count -gt 0) {
        Fail "Refusing to commit sensitive/generated paths:`n - $($blocked -join "`n - ")"
    }

    if ($largeFiles.Count -gt 0) {
        Fail "Refusing to commit files larger than $([math]::Round($MaxFileBytes / 1MB, 2)) MB:`n - $($largeFiles -join "`n - ")"
    }
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptRoot "..")
Set-Location $repoRoot

$actualRepoRoot = (Get-GitOutput @("rev-parse", "--show-toplevel") | Select-Object -First 1)
if ((Resolve-Path $actualRepoRoot).Path -ne $repoRoot.Path) {
    Fail "This script must run inside the MoneyPrinterTurbo child Git repository."
}

$branch = (Get-GitOutput @("branch", "--show-current") | Select-Object -First 1)
if ([string]::IsNullOrWhiteSpace($branch)) {
    Fail "Detached HEAD detected. Checkout a branch before using auto push."
}

$remote = ""
try {
    $remote = (& git remote get-url origin 2>$null | Select-Object -First 1)
} catch {
    $remote = ""
}

if ([string]::IsNullOrWhiteSpace($remote)) {
    Fail "No origin remote is configured. Create a private repository, then run: git remote add origin <private-repo-url>"
}

if (-not $AllowUpstreamOrigin -and $remote -match "github\.com[:/]harry0703/MoneyPrinterTurbo(\.git)?$") {
    Fail "origin points to the public upstream repo. Set origin to your private repo first, or rerun with -AllowUpstreamOrigin if you really intend this."
}

$status = Get-GitOutput @("status", "--short")
if ($status.Count -eq 0) {
    Write-Host "No changes to commit."
    exit 0
}

Write-Host "Repository: $repoRoot"
Write-Host "Branch:     $branch"
Write-Host "Origin:     $remote"
Write-Host ""
Write-Host "Current changes:"
$status | ForEach-Object { Write-Host $_ }
Write-Host ""

$statusPaths = Get-StatusPaths
Assert-SafePaths -Paths $statusPaths -RepoRoot $repoRoot -MaxFileBytes $MaxFileBytes

if ([string]::IsNullOrWhiteSpace($Message)) {
    $Message = "Auto commit $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
}

if ($DryRun) {
    Write-Host "DRY RUN: safety checks passed."
    Write-Host "DRY RUN: would run git add -A"
    Write-Host "DRY RUN: would commit with message: $Message"
    Write-Host "DRY RUN: would push origin $branch"
    exit 0
}

Invoke-Git @("add", "-A")

$stagedPaths = Get-GitOutput @("diff", "--cached", "--name-only")
if ($stagedPaths.Count -eq 0) {
    Write-Host "No staged changes to commit."
    exit 0
}

Assert-SafePaths -Paths $stagedPaths -RepoRoot $repoRoot -MaxFileBytes $MaxFileBytes

Invoke-Git @("commit", "-m", $Message)
Invoke-Git @("push", "origin", $branch)

Write-Host "Pushed $branch to origin successfully."
