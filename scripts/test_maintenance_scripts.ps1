[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$SafePushScript = Join-Path $RepoRoot "scripts\git_safe_push_main.ps1"
$ChecksScript = Join-Path $RepoRoot "scripts\run_maintenance_checks.ps1"

function Assert-True {
    param(
        [bool]$Condition,
        [string]$Message
    )

    if (-not $Condition) {
        throw $Message
    }
}

function Assert-Contains {
    param(
        [string]$Text,
        [string]$Expected,
        [string]$Message
    )

    if ($Text -notlike "*$Expected*") {
        throw "$Message`nExpected to find: $Expected`nActual: $Text"
    }
}

function Invoke-GitChecked {
    param(
        [string]$WorkDir,
        [string[]]$Arguments
    )

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & git -C $WorkDir @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    if ($exitCode -ne 0) {
        throw "git -C $WorkDir $($Arguments -join ' ') failed: $output"
    }
    return $output
}

function New-TestGitRepository {
    $testRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("videoturn-maintenance-test-" + [guid]::NewGuid().ToString("N"))
    $repo = Join-Path $testRoot "repo"
    $remote = Join-Path $testRoot "remote.git"

    New-Item -ItemType Directory -Path $repo -Force | Out-Null
    Invoke-GitChecked -WorkDir $repo -Arguments @("init", "-b", "main") | Out-Null
    Invoke-GitChecked -WorkDir $repo -Arguments @("config", "core.autocrlf", "false") | Out-Null
    Invoke-GitChecked -WorkDir $repo -Arguments @("config", "user.email", "codex-test@example.invalid") | Out-Null
    Invoke-GitChecked -WorkDir $repo -Arguments @("config", "user.name", "Codex Test") | Out-Null

    Set-Content -Path (Join-Path $repo "README.md") -Value "# Test Repo`n" -Encoding UTF8
    Invoke-GitChecked -WorkDir $repo -Arguments @("add", "README.md") | Out-Null
    Invoke-GitChecked -WorkDir $repo -Arguments @("commit", "-m", "initial") | Out-Null

    & git init --bare $remote 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "git init --bare failed"
    }

    Invoke-GitChecked -WorkDir $repo -Arguments @("remote", "add", "origin", $remote) | Out-Null
    Invoke-GitChecked -WorkDir $repo -Arguments @("push", "-u", "origin", "main") | Out-Null

    return [pscustomobject]@{
        Root = $testRoot
        Repo = $repo
        Remote = $remote
    }
}

function New-PassingCheckScript {
    param([string]$Directory)

    $path = Join-Path $Directory "pass-check.ps1"
    Set-Content -Path $path -Value "exit 0`n" -Encoding UTF8
    return $path
}

function Invoke-ScriptProcess {
    param([string[]]$Arguments)

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & powershell @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = ($output -join "`n")
    }
}

function Invoke-WithTempRepo {
    param([scriptblock]$Body)

    $fixture = New-TestGitRepository
    try {
        & $Body $fixture
    } finally {
        $tempRoot = [System.IO.Path]::GetTempPath()
        $resolvedRoot = [System.IO.Path]::GetFullPath($fixture.Root)
        Assert-True -Condition ($resolvedRoot.StartsWith($tempRoot, [System.StringComparison]::OrdinalIgnoreCase)) -Message "Refusing to remove non-temp path: $resolvedRoot"
        Remove-Item -LiteralPath $fixture.Root -Recurse -Force
    }
}

function Test-SafePushRequiresCleanBaseline {
    Invoke-WithTempRepo {
        param($fixture)

        $baseline = Join-Path $fixture.Root "baseline.txt"
        Set-Content -Path $baseline -Value " M README.md`n" -Encoding UTF8
        $checkScript = New-PassingCheckScript -Directory $fixture.Root
        Add-Content -Path (Join-Path $fixture.Repo "README.md") -Value "dirty before automation"

        $result = Invoke-ScriptProcess -Arguments @(
            "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", $SafePushScript,
            "-RepoRoot", $fixture.Repo,
            "-ExpectedRemoteUrl", $fixture.Remote,
            "-BaselineStatusPath", $baseline,
            "-CheckScriptPath", $checkScript,
            "-Message", "auto-maintenance: test"
        )

        Assert-True -Condition ($result.ExitCode -ne 0) -Message "Expected dirty baseline to fail."
        Assert-Contains -Text $result.Output -Expected "Baseline status is not clean" -Message "Expected baseline failure message."
    }
}

function Test-SafePushRejectsBaselineInsideRepository {
    Invoke-WithTempRepo {
        param($fixture)

        $baseline = Join-Path $fixture.Repo "baseline.txt"
        Set-Content -Path $baseline -Value "" -Encoding UTF8
        $checkScript = New-PassingCheckScript -Directory $fixture.Root

        $result = Invoke-ScriptProcess -Arguments @(
            "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", $SafePushScript,
            "-RepoRoot", $fixture.Repo,
            "-ExpectedRemoteUrl", $fixture.Remote,
            "-BaselineStatusPath", $baseline,
            "-CheckScriptPath", $checkScript,
            "-Message", "auto-maintenance: test"
        )

        Assert-True -Condition ($result.ExitCode -ne 0) -Message "Expected an in-repository baseline file to fail."
        Assert-Contains -Text $result.Output -Expected "Baseline status file must be outside the repository" -Message "Expected baseline path boundary failure message."
    }
}

function Test-SafePushBlocksSensitivePath {
    Invoke-WithTempRepo {
        param($fixture)

        $baseline = Join-Path $fixture.Root "baseline.txt"
        Set-Content -Path $baseline -Value "" -Encoding UTF8
        $checkScript = New-PassingCheckScript -Directory $fixture.Root
        Set-Content -Path (Join-Path $fixture.Repo "client_secret_test.json") -Value "{}" -Encoding UTF8

        $result = Invoke-ScriptProcess -Arguments @(
            "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", $SafePushScript,
            "-RepoRoot", $fixture.Repo,
            "-ExpectedRemoteUrl", $fixture.Remote,
            "-BaselineStatusPath", $baseline,
            "-CheckScriptPath", $checkScript,
            "-Message", "auto-maintenance: test"
        )

        Assert-True -Condition ($result.ExitCode -ne 0) -Message "Expected sensitive path to fail."
        Assert-Contains -Text $result.Output -Expected "Refusing to commit sensitive/generated paths" -Message "Expected sensitive path failure message."
    }
}

function Test-SafePushBlocksLocalSecretConfigNames {
    Invoke-WithTempRepo {
        param($fixture)

        $baseline = Join-Path $fixture.Root "baseline.txt"
        Set-Content -Path $baseline -Value "" -Encoding UTF8
        $checkScript = New-PassingCheckScript -Directory $fixture.Root
        Set-Content -Path (Join-Path $fixture.Repo "prod.env") -Value "SECRET=value" -Encoding UTF8
        Set-Content -Path (Join-Path $fixture.Repo "config.local.toml") -Value "secret = `"value`"" -Encoding UTF8

        $result = Invoke-ScriptProcess -Arguments @(
            "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", $SafePushScript,
            "-RepoRoot", $fixture.Repo,
            "-ExpectedRemoteUrl", $fixture.Remote,
            "-BaselineStatusPath", $baseline,
            "-CheckScriptPath", $checkScript,
            "-Message", "auto-maintenance: test"
        )

        Assert-True -Condition ($result.ExitCode -ne 0) -Message "Expected local secret config names to fail."
        Assert-Contains -Text $result.Output -Expected "Refusing to commit sensitive/generated paths" -Message "Expected sensitive path failure message."
        Assert-Contains -Text $result.Output -Expected "prod.env" -Message "Expected env file to be blocked."
        Assert-Contains -Text $result.Output -Expected "config.local.toml" -Message "Expected local config file to be blocked."
    }
}

function Test-SafePushBlocksOAuthTokenJsonNames {
    Invoke-WithTempRepo {
        param($fixture)

        $baseline = Join-Path $fixture.Root "baseline.txt"
        Set-Content -Path $baseline -Value "" -Encoding UTF8
        $checkScript = New-PassingCheckScript -Directory $fixture.Root
        Set-Content -Path (Join-Path $fixture.Repo "youtube_token.json") -Value "{}" -Encoding UTF8
        Set-Content -Path (Join-Path $fixture.Repo "credentials.json") -Value "{}" -Encoding UTF8

        $result = Invoke-ScriptProcess -Arguments @(
            "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", $SafePushScript,
            "-RepoRoot", $fixture.Repo,
            "-ExpectedRemoteUrl", $fixture.Remote,
            "-BaselineStatusPath", $baseline,
            "-CheckScriptPath", $checkScript,
            "-Message", "auto-maintenance: test"
        )

        Assert-True -Condition ($result.ExitCode -ne 0) -Message "Expected OAuth token JSON names to fail."
        Assert-Contains -Text $result.Output -Expected "Refusing to commit sensitive/generated paths" -Message "Expected sensitive path failure message."
        Assert-Contains -Text $result.Output -Expected "youtube_token.json" -Message "Expected token file to be blocked."
        Assert-Contains -Text $result.Output -Expected "credentials.json" -Message "Expected credentials file to be blocked."
    }
}

function Test-SafePushBlocksOAuthTokenPickleNames {
    Invoke-WithTempRepo {
        param($fixture)

        $baseline = Join-Path $fixture.Root "baseline.txt"
        Set-Content -Path $baseline -Value "" -Encoding UTF8
        $checkScript = New-PassingCheckScript -Directory $fixture.Root
        Set-Content -Path (Join-Path $fixture.Repo "youtube_token.pickle") -Value "serialized-token" -Encoding UTF8
        Set-Content -Path (Join-Path $fixture.Repo "credentials.pkl") -Value "serialized-credentials" -Encoding UTF8

        $result = Invoke-ScriptProcess -Arguments @(
            "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", $SafePushScript,
            "-RepoRoot", $fixture.Repo,
            "-ExpectedRemoteUrl", $fixture.Remote,
            "-BaselineStatusPath", $baseline,
            "-CheckScriptPath", $checkScript,
            "-Message", "auto-maintenance: test"
        )

        Assert-True -Condition ($result.ExitCode -ne 0) -Message "Expected OAuth token pickle names to fail."
        Assert-Contains -Text $result.Output -Expected "Refusing to commit sensitive/generated paths" -Message "Expected sensitive path failure message."
        Assert-Contains -Text $result.Output -Expected "youtube_token.pickle" -Message "Expected token pickle file to be blocked."
        Assert-Contains -Text $result.Output -Expected "credentials.pkl" -Message "Expected credentials pickle file to be blocked."
    }
}

function Test-SafePushRejectsCheckScriptMutation {
    Invoke-WithTempRepo {
        param($fixture)

        $baseline = Join-Path $fixture.Root "baseline.txt"
        Set-Content -Path $baseline -Value "" -Encoding UTF8
        $checkScript = Join-Path $fixture.Root "mutating-check.ps1"
        Set-Content -Path $checkScript -Value "Add-Content -Path '$($fixture.Repo)\README.md' -Value 'changed by check'`nexit 0`n" -Encoding UTF8
        Add-Content -Path (Join-Path $fixture.Repo "README.md") -Value "safe change"

        $result = Invoke-ScriptProcess -Arguments @(
            "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", $SafePushScript,
            "-RepoRoot", $fixture.Repo,
            "-ExpectedRemoteUrl", $fixture.Remote,
            "-BaselineStatusPath", $baseline,
            "-CheckScriptPath", $checkScript,
            "-Message", "auto-maintenance: test"
        )

        Assert-True -Condition ($result.ExitCode -ne 0) -Message "Expected check-script repository mutation to fail."
        Assert-Contains -Text $result.Output -Expected "Maintenance checks modified repository changes" -Message "Expected check mutation failure message."
    }
}

function Test-SafePushCommitsAndPushesMain {
    Invoke-WithTempRepo {
        param($fixture)

        $baseline = Join-Path $fixture.Root "baseline.txt"
        Set-Content -Path $baseline -Value "" -Encoding UTF8
        $checkScript = New-PassingCheckScript -Directory $fixture.Root
        Add-Content -Path (Join-Path $fixture.Repo "README.md") -Value "safe change"

        $result = Invoke-ScriptProcess -Arguments @(
            "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", $SafePushScript,
            "-RepoRoot", $fixture.Repo,
            "-ExpectedRemoteUrl", $fixture.Remote,
            "-BaselineStatusPath", $baseline,
            "-CheckScriptPath", $checkScript,
            "-Message", "auto-maintenance: test push"
        )

        Assert-True -Condition ($result.ExitCode -eq 0) -Message "Expected safe push to succeed. Output: $($result.Output)"
        Assert-Contains -Text $result.Output -Expected "Pushed main to origin successfully" -Message "Expected push success message."

        $localHead = Invoke-GitChecked -WorkDir $fixture.Repo -Arguments @("rev-parse", "HEAD") | Select-Object -First 1
        $remoteHead = & git --git-dir $fixture.Remote rev-parse main
        Assert-True -Condition ($localHead -eq $remoteHead) -Message "Expected local and remote main to match."
    }
}

function Test-RunMaintenanceChecksRejectsInvalidPowerShellSyntax {
    Invoke-WithTempRepo {
        param($fixture)

        $scriptDir = Join-Path $fixture.Repo "scripts"
        New-Item -ItemType Directory -Path $scriptDir -Force | Out-Null
        Set-Content -Path (Join-Path $scriptDir "bad.ps1") -Value "if (`$true) {`n" -Encoding UTF8

        $result = Invoke-ScriptProcess -Arguments @(
            "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", $ChecksScript,
            "-RepoRoot", $fixture.Repo,
            "-SkipPythonTests"
        )

        Assert-True -Condition ($result.ExitCode -ne 0) -Message "Expected invalid PowerShell syntax to fail."
        Assert-Contains -Text $result.Output -Expected "PowerShell syntax errors" -Message "Expected syntax failure message."
    }
}

function Test-RunMaintenanceChecksRunsMaintenanceScriptTests {
    Invoke-WithTempRepo {
        param($fixture)

        $probeScript = Join-Path $fixture.Root "maintenance-tests-probe.ps1"
        Set-Content -Path $probeScript -Value "Write-Host 'maintenance script tests invoked'`nexit 0`n" -Encoding UTF8

        $result = Invoke-ScriptProcess -Arguments @(
            "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", $ChecksScript,
            "-RepoRoot", $fixture.Repo,
            "-SkipPythonTests",
            "-MaintenanceScriptTestsPath", $probeScript
        )

        Assert-True -Condition ($result.ExitCode -eq 0) -Message "Expected maintenance script tests to run. Output: $($result.Output)"
        Assert-Contains -Text $result.Output -Expected "maintenance script tests invoked" -Message "Expected maintenance script test output."
    }
}

$tests = @(
    "Test-SafePushRequiresCleanBaseline",
    "Test-SafePushRejectsBaselineInsideRepository",
    "Test-SafePushBlocksSensitivePath",
    "Test-SafePushBlocksLocalSecretConfigNames",
    "Test-SafePushBlocksOAuthTokenJsonNames",
    "Test-SafePushBlocksOAuthTokenPickleNames",
    "Test-SafePushRejectsCheckScriptMutation",
    "Test-SafePushCommitsAndPushesMain",
    "Test-RunMaintenanceChecksRejectsInvalidPowerShellSyntax",
    "Test-RunMaintenanceChecksRunsMaintenanceScriptTests"
)

foreach ($test in $tests) {
    Write-Host "Running $test..."
    & $test
}

Write-Host "All maintenance script tests passed."
