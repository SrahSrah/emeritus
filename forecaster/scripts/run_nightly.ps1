<#
.SYNOPSIS
    Nightly Forecaster run, for Windows Task Scheduler (FR-14).

.DESCRIPTION
    Strips ANTHROPIC_API_KEY before anything else — if it is set it shadows
    CLAUDE_CODE_OAUTH_TOKEN and the run would silently bill per token. Loads the
    gitignored .env, invokes the CLI, tees stdout and stderr to a timestamped log under
    the gitignored data\, and exits non-zero on failure so Task Scheduler records it.

    The log never contains a secret: .env values are loaded into the process environment
    and are never echoed.

.PARAMETER DryRun
    Pass --dry-run through to the CLI: fake deliverer (nothing is sent), real agent
    client, still writes the trace. This is how the script is verified without mail.

.EXAMPLE
    .\scripts\run_nightly.ps1 -DryRun

.NOTES
    Registering the scheduled task is a human action — see README.md. A sleeping laptop
    at 7 pm produces no digest and no error; the CLI records intended-but-missed slots as
    `missed_run` trace records so the delivery metric stays honest (PRD §8 / §2b).
#>

[CmdletBinding()]
param(
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

# 1. Strip the shadowing key BEFORE anything else.
Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue

# 2. Locate the project (this script lives in <project>\scripts).
$ProjectDir = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectDir

# 3. Load the gitignored .env into the process environment. Values are never echoed.
$EnvFile = Join-Path $ProjectDir '.env'
if (Test-Path $EnvFile) {
    foreach ($line in Get-Content $EnvFile) {
        $trimmed = $line.Trim()
        if ($trimmed -eq '' -or $trimmed.StartsWith('#')) { continue }
        $split = $trimmed.IndexOf('=')
        if ($split -lt 1) { continue }
        $name = $trimmed.Substring(0, $split).Trim()
        $value = $trimmed.Substring($split + 1).Trim().Trim('"')
        if ($name -eq 'ANTHROPIC_API_KEY') { continue }  # never, from any source
        if ($value -ne '') {
            Set-Item -Path "Env:$name" -Value $value
        }
    }
}

# 4. Prepare the log. data\ is gitignored.
$LogDir = Join-Path $ProjectDir 'data\logs'
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$LogFile = Join-Path $LogDir "nightly-$Stamp.log"

$CliArgs = @('run', 'python', '-m', 'forecaster.cli')
if ($DryRun) { $CliArgs += '--dry-run' }

"=== Forecaster nightly run $Stamp ===" | Out-File -FilePath $LogFile -Encoding utf8
"project: $ProjectDir"                  | Out-File -FilePath $LogFile -Encoding utf8 -Append
"dry-run: $($DryRun.IsPresent)"          | Out-File -FilePath $LogFile -Encoding utf8 -Append
"ANTHROPIC_API_KEY present: $([bool](Get-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue))" |
    Out-File -FilePath $LogFile -Encoding utf8 -Append
"CLAUDE_CODE_OAUTH_TOKEN present: $([bool](Get-Item Env:CLAUDE_CODE_OAUTH_TOKEN -ErrorAction SilentlyContinue))" |
    Out-File -FilePath $LogFile -Encoding utf8 -Append

# 5. Run, capturing both streams. Never echo a secret.
#
#    Start-Process with explicit redirect files rather than `*>&1`: in Windows
#    PowerShell 5.1, piping a native command's stderr wraps every line in an ErrorRecord
#    and Tee-Object writes UTF-16 into a UTF-8 log, which produced an unreadable file.
$ErrorActionPreference = 'Continue'
$OutFile = "$LogFile.out.tmp"
$ErrFile = "$LogFile.err.tmp"

$Process = Start-Process -FilePath 'uv' -ArgumentList $CliArgs -NoNewWindow -Wait -PassThru `
    -RedirectStandardOutput $OutFile -RedirectStandardError $ErrFile
$ExitCode = $Process.ExitCode

foreach ($stream in @(@('stdout', $OutFile), @('stderr', $ErrFile))) {
    if (Test-Path $stream[1]) {
        $content = Get-Content $stream[1] -Raw
        if ($content -and $content.Trim() -ne '') {
            "--- $($stream[0]) ---" | Out-File -FilePath $LogFile -Encoding utf8 -Append
            $content.TrimEnd()      | Out-File -FilePath $LogFile -Encoding utf8 -Append
            Write-Output $content.TrimEnd()
        }
        Remove-Item $stream[1] -ErrorAction SilentlyContinue
    }
}

"exit code: $ExitCode" | Out-File -FilePath $LogFile -Encoding utf8 -Append
Write-Output "log: $LogFile"

exit $ExitCode
