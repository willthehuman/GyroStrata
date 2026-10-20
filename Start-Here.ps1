# One-click setup: model download (own window, with progress) and engine build at the same time, then install, tune
# and a ready launcher. Each step is the same tool the separate CMD files run; rerunning resumes where it stopped.
param(
    [Parameter(Position = 0)][string]$ModelDir,
    [ValidateSet('exact', 'balanced', 'fast')][string]$Quality = 'balanced',
    [switch]$QuickTune,
    [switch]$NoTune
)
# Native tools report on stderr; their exit codes are checked explicitly (PowerShell 5.1 would treat stderr as fatal).
$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$FileName = 'Qwen3.8-Flash-Next-Gyro-M-TQ2_0.gguf'

function Step([string]$Number, [string]$Text) {
    Write-Host ''
    Write-Host "[$Number/5] $Text" -ForegroundColor Cyan
}

function Find-Python {
    if ($env:GYRO_PYTHON) { return $env:GYRO_PYTHON }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($Version in '3.14', '3.13', '3.12') {
            $Found = & py "-$Version" -c 'import sys;print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $Found) { return ([string]$Found).Trim() }
        }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) { return 'python' }
    return $null
}

function Show-Prerequisites {
    Write-Host ''
    Write-Host 'Fix the problem named above, then open START-HERE.cmd again (the download continues where it stopped).' -ForegroundColor Yellow
    Write-Host 'The engine build needs:'
    Write-Host '  Git for Windows        https://git-scm.com/downloads/win'
    Write-Host '  Python 3.12-3.14       https://www.python.org/downloads/windows/'
    Write-Host '  VS 2022 Build Tools    https://aka.ms/vs/17/release/vs_BuildTools.exe  (Desktop development with C++)'
    Write-Host '  CUDA Toolkit 13.2      https://developer.nvidia.com/cuda-toolkit-archive  (Update 2+ for RTX 50-series)'
    Write-Host '  NVIDIA driver R580 or newer'
}

try {
    Write-Host 'GyroStrata setup: Gyro-M on a 12 GB GPU and 32 GB RAM.' -ForegroundColor Green
    Write-Host 'The model download (about 86 GiB) and the engine build run at the same time. Plan for 1-2 hours;'
    Write-Host 'you can close this window at any point and open START-HERE.cmd again to continue.'

    Step 1 'Model folder'
    if ([string]::IsNullOrWhiteSpace($ModelDir)) {
        $Saved = Join-Path $Root '.model-dir'
        Add-Type -AssemblyName System.Windows.Forms
        $Picker = New-Object System.Windows.Forms.FolderBrowserDialog
        $Picker.Description = 'Choose a folder on an SSD for Gyro-M (about 120 GiB with its expert pack).'
        $Picker.ShowNewFolderButton = $true
        if (Test-Path -LiteralPath $Saved) { $Picker.SelectedPath = (Get-Content -LiteralPath $Saved -Raw -ErrorAction Stop).Trim() }
        try {
            if ($Picker.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { throw 'No folder was chosen.' }
            $ModelDir = $Picker.SelectedPath
        }
        finally { $Picker.Dispose() }
    }
    $ModelDir = [IO.Path]::GetFullPath($ModelDir)
    Write-Host "  $ModelDir"

    Step 2 'Checking the tools this PC needs to build the engine'
    $Python = Find-Python
    $Ready = $false
    if ($Python) {
        & $Python (Join-Path $Root 'setup.py') --check
        $Ready = $LASTEXITCODE -eq 0
    }
    else { Write-Host '  Python 3.12-3.14 was not found.' }

    Step 3 'Downloading the model in a second window (progress is shown there)'
    # A download left running by an earlier start (for example while a missing tool was installed) holds this lock:
    # wait for that window rather than start a second downloader, which the lock would refuse.
    $Lock = Join-Path $ModelDir '.gyro-download.lock'
    while (Test-Path -LiteralPath $Lock) {
        try { [IO.File]::Open($Lock, 'Open', 'ReadWrite', 'None').Dispose(); break }   # stale lock: no downloader
        catch { Write-Host '  A download from an earlier start is still running; waiting for it...'; Start-Sleep 30 }
    }
    $Downloader = Join-Path $Root 'Download-Gyro-M.ps1'
    $Inner = "& '$($Downloader.Replace("'", "''"))' '$($ModelDir.Replace("'", "''"))'; `$c = `$LASTEXITCODE; " +
             "if (`$c) { Read-Host 'The download stopped. Press Enter to close this window' }; exit `$c"
    $Download = Start-Process powershell.exe -PassThru -ErrorAction Stop -ArgumentList @(
        '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-Command', $Inner)

    if (-not $Ready) {
        Show-Prerequisites
        Write-Host ''
        Write-Host 'The download keeps running in its window meanwhile.' -ForegroundColor Yellow
        $Download.WaitForExit()
        exit 1
    }

    Step 4 'Building the engine while the model downloads (about 20-40 minutes)'
    & $Python (Join-Path $Root 'setup.py') --build-only
    if ($LASTEXITCODE -ne 0) { throw 'The engine build stopped; read the error above.' }

    Write-Host ''
    Write-Host 'Waiting for the download to finish...'
    $Download.WaitForExit()
    if ($Download.ExitCode -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $ModelDir $FileName))) {
        throw 'The download did not finish. Open START-HERE.cmd again to resume it.'
    }

    Step 5 'Installing the model, then measuring this PC for the fastest settings (about 10-15 minutes)'
    # The downloader has just checked the file's SHA256, so the installer does not read all 86 GiB again.
    $InstallArgs = @((Join-Path $Root 'setup.py'), '--model-dir', $ModelDir, '--skip-weight-hash')
    if (Test-Path -LiteralPath (Join-Path $ModelDir '.gyro-recipe\api-key.txt')) { $InstallArgs += '--api-key' }   # keep an existing key
    & $Python @InstallArgs
    if ($LASTEXITCODE -ne 0) { throw 'Installation stopped; read the error above.' }
    if (-not $NoTune) {
        $TuneArgs = @((Join-Path $Root 'tune.py'), '--model-dir', $ModelDir, '--quality', $Quality, '--skip-if-current')
        if ($QuickTune) { $TuneArgs += '--quick' }
        & (Join-Path $Root '.venv\Scripts\python.exe') @TuneArgs
        if ($LASTEXITCODE -ne 0) {
            Write-Host 'Tuning did not finish; the launcher uses the shipped defaults. Run TUNE.cmd later to retry.' -ForegroundColor Yellow
        }
    }

    $Launcher = Join-Path $ModelDir 'Start-Gyro-M-256K.cmd'
    Write-Host ''
    Write-Host 'Ready.' -ForegroundColor Green
    Write-Host "Start the model any time with: $Launcher"
    Write-Host 'API: http://127.0.0.1:8080/v1   model: qwen38-gyro-m'
    if (-not [Console]::IsInputRedirected) {
        $Answer = Read-Host 'Start Gyro-M now? [Y/n]'
        if ($Answer -notmatch '^[nN]') { Start-Process -FilePath $Launcher -WorkingDirectory $ModelDir }
    }
}
catch {
    Write-Host ''
    Write-Host ('Setup stopped: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
