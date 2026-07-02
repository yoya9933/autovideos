[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [switch]$SkipPythonTests
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

function Test-PowerShellSyntax {
    param([string[]]$Paths)

    $failures = @()
    foreach ($path in $Paths) {
        if ($path -notlike "*.ps1") {
            continue
        }

        $fullPath = Join-Path $script:RepoRootPath ($path -replace "/", "\")
        if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
            continue
        }

        $tokens = $null
        $errors = $null
        [System.Management.Automation.Language.Parser]::ParseFile($fullPath, [ref]$tokens, [ref]$errors) | Out-Null
        if ($errors -and $errors.Count -gt 0) {
            $messages = $errors | ForEach-Object { "${path}:$($_.Extent.StartLineNumber): $($_.Message)" }
            $failures += $messages
        }
    }

    if ($failures.Count -gt 0) {
        Fail "PowerShell syntax errors:`n$($failures -join "`n")"
    }
}

function Test-XmlSyntax {
    param([string[]]$Paths)

    $failures = @()
    foreach ($path in $Paths) {
        if ($path -notlike "*.xml") {
            continue
        }

        $fullPath = Join-Path $script:RepoRootPath ($path -replace "/", "\")
        if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
            continue
        }

        try {
            [xml](Get-Content -LiteralPath $fullPath -Raw) | Out-Null
        } catch {
            $failures += "${path}: $($_.Exception.Message)"
        }
    }

    if ($failures.Count -gt 0) {
        Fail "XML syntax errors:`n$($failures -join "`n")"
    }
}

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Join-Path $PSScriptRoot ".."
}

$script:RepoRootPath = (Resolve-Path $RepoRoot).Path
Set-Location $script:RepoRootPath

$actualRepoRoot = (Invoke-Git @("rev-parse", "--show-toplevel") | Select-Object -First 1)
if ((Resolve-Path $actualRepoRoot).Path -ne $script:RepoRootPath) {
    Fail "RepoRoot is not the active Git root. Expected $script:RepoRootPath but git reported $actualRepoRoot."
}

Write-Host "Running git whitespace checks..."
Invoke-Git @("diff", "--check") | Out-Null
Invoke-Git @("diff", "--cached", "--check") | Out-Null

$changedPaths = Get-StatusPaths
if ($changedPaths.Count -gt 0) {
    Write-Host "Checking changed PowerShell and XML files..."
    Test-PowerShellSyntax -Paths $changedPaths
    Test-XmlSyntax -Paths $changedPaths
}

if (-not $SkipPythonTests) {
    $appRoot = Join-Path $script:RepoRootPath "MoneyPrinterTurbo-Portable-Windows-1.2.6\MoneyPrinterTurbo"
    $pythonPath = Join-Path $script:RepoRootPath "MoneyPrinterTurbo-Portable-Windows-1.2.6\lib\python\python.exe"

    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
        Fail "Portable Python was not found: $pythonPath"
    }
    if (-not (Test-Path -LiteralPath $appRoot -PathType Container)) {
        Fail "MoneyPrinterTurbo app root was not found: $appRoot"
    }

    Write-Host "Running MoneyPrinterTurbo unittest suite..."
    Push-Location $appRoot
    $previousPythonIoEncoding = $env:PYTHONIOENCODING
    $previousPythonUtf8 = $env:PYTHONUTF8
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"
    try {
        Invoke-External `
            -Command $pythonPath `
            -Arguments @("-m", "unittest", "discover", "-s", "test") `
            -FailureMessage "MoneyPrinterTurbo unittest suite failed." | Out-Null
    } finally {
        $env:PYTHONIOENCODING = $previousPythonIoEncoding
        $env:PYTHONUTF8 = $previousPythonUtf8
        Pop-Location
    }
}

Write-Host "Maintenance checks passed."
