$ErrorActionPreference = 'Stop'

$Project = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$EngineSource = Join-Path (Split-Path -Parent $Project) 'metal_remover'
$Python = Join-Path $Project 'tests\venv_notorch\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "cleanCT test interpreter not found: $Python"
}

$ScratchParentRaw = $env:CLEANCT_REGRESSION_SCRATCH_ROOT
if ([string]::IsNullOrWhiteSpace($ScratchParentRaw)) {
    $ScratchParentRaw = [System.IO.Path]::GetTempPath()
}
$ScratchParent = [System.IO.Path]::GetFullPath($ScratchParentRaw)
$Scratch = Join-Path $ScratchParent ("cleanct-regression-" + [guid]::NewGuid().ToString('N'))
$Engine = Join-Path $Scratch 'engine'
$Data = Join-Path $Scratch 'data'
$TestTmp = Join-Path $Scratch 'tmp'
$EngineModules = @('tomograph.py', 'roi_delivery.py', 'wood_track.py', 'air_crop.py', 'gpu_backend.py', 'volume_io.py')
$Tests = @('test_checkpoint_file.py', 'test_viewer_regressions.py', 'test_render_async.py', 'test_specimen_panel.py', 'test_wood_bounds.py', 'test_auto_snap.py', 'test_unproc_and_frames.py', 'test_export_formats.py', 'test_export_stream.py', 'test_nifti_roundtrip.py', 'test_state_files.py', 'test_viewer_cache.py', 'test_pipeline_synthetic.py', 'test_volume_inputs.py', 'test_launcher_paths.py', 'test_installer_icons.py', 'test_installer_script.py', 'test_theme.py', 'test_user_messages.py', 'test_dialogs.py', 'test_theme_tokens.py', 'test_settings_page.py', 'test_layout_fit.py', 'test_controls_paint.py')
$EnvNames = @('CLEANCT_APP_ROOT', 'CLEANCT_ENGINE', 'CLEANCT_DATA', 'CLEANCT_TEST_TMP_DIR', 'CLEANCT_OUTPUT_ROOT', 'CLEANCT_REGRESSION_SCRATCH_ROOT', 'QT_QPA_PLATFORM', 'PYTHONUTF8', 'PYTHONPATH', 'TEMP', 'TMP')
$PreviousEnv = @{}
foreach ($Name in $EnvNames) {
    $PreviousEnv[$Name] = [Environment]::GetEnvironmentVariable($Name, 'Process')
}

try {
    New-Item -ItemType Directory -Path $Engine, $Data, $TestTmp -Force | Out-Null
    foreach ($Name in $EngineModules) {
        $Source = Join-Path $EngineSource $Name
        if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
            throw "Required processing source is missing: $Source"
        }
        Copy-Item -LiteralPath $Source -Destination $Engine
    }

    $env:CLEANCT_APP_ROOT = $Project
    $env:CLEANCT_ENGINE = $Engine
    $env:CLEANCT_DATA = $Data
    $env:CLEANCT_TEST_TMP_DIR = $TestTmp
    $env:CLEANCT_OUTPUT_ROOT = Join-Path $Engine 'pipeline_output'
    $env:QT_QPA_PLATFORM = 'offscreen'
    $env:PYTHONUTF8 = '1'
    # structured checkout: app sources live in src\ (packaged payload keeps
    # its flat app\ layout, which needs no PYTHONPATH)
    $env:PYTHONPATH = "$Project;$Project\src"
    $env:TEMP = $TestTmp
    $env:TMP = $TestTmp

    foreach ($Name in $Tests) {
        $TestPath = Join-Path $PSScriptRoot $Name
        Write-Host "Running $Name"
        & $Python $TestPath
        if ($LASTEXITCODE -ne 0) {
            throw "$Name failed with exit code $LASTEXITCODE"
        }
    }
    Write-Host 'cleanCT focused regression suite: PASS'
}
finally {
    foreach ($Name in $EnvNames) {
        if ($null -eq $PreviousEnv[$Name]) {
            Remove-Item -LiteralPath "Env:$Name" -ErrorAction SilentlyContinue
        } else {
            [Environment]::SetEnvironmentVariable($Name, $PreviousEnv[$Name], 'Process')
        }
    }

    $ResolvedScratch = [System.IO.Path]::GetFullPath($Scratch).TrimEnd('\')
    $ResolvedParent = $ScratchParent.TrimEnd('\') + '\'
    if (-not $ResolvedScratch.StartsWith($ResolvedParent, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean scratch path outside the temporary directory: $ResolvedScratch"
    }
    if (Test-Path -LiteralPath $ResolvedScratch) {
        Remove-Item -LiteralPath $ResolvedScratch -Recurse -Force
    }
}
