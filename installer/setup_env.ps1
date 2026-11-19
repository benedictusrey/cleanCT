# installer/setup_env.ps1 — cleanCT 1.0.0 pinned dependency installer
#
# Installs the exact audited dependency set (audit rounds 0A-0P) into any
# CPython 3.12 environment. Used by installer/build_installer.py to populate
# the embedded runtime, and standalone to recreate a dev environment:
#
#   powershell -ExecutionPolicy Bypass -File setup_env.ps1 [path\to\python.exe]
#
# GPU acceleration uses CuPy (cupy-cuda12x + the small NVRTC wheel) instead
# of the ~4 GB PyTorch/CUDA payload: the engine's CuPy backend covers the
# full GPU surface used by the pipeline, and a torch-free environment makes
# CuPy's NVRTC self-consistent (torch's NVRTC is known to shadow it).
# Any machine without an NVIDIA GPU simply runs the validated CPU backend.
#
# Versions are the exact set the app was audited and validated against.

$ErrorActionPreference = "Stop"

$PY = if ($args.Count -ge 1) { $args[0] } else { "python" }
if (-not (Get-Command $PY -ErrorAction SilentlyContinue) -and -not (Test-Path $PY)) {
    Write-Error "python not found: $PY"
    exit 1
}

Write-Host "== cleanCT pinned dependencies -> $PY =="
& $PY -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip failed: upgrading pip" }

# Core scientific + imaging stack (audited versions, zero drift)
& $PY -m pip install -r "$PSScriptRoot\requirements-core.txt"
if ($LASTEXITCODE -ne 0) { throw "pip failed: core scientific and imaging stack" }

# GPU stack: CuPy for CUDA 12.x + the NVRTC wheel it JITs with.
# The NVRTC/runtime DLL payload is substantial but self-contained; no
# CUDA Toolkit installation is required on the target PC.  nvrtc MUST be
# 12.8.93: that wheel is the self-consistent
# pair (NVRTC 12.8.93 + nvrtc-builtins64_128.dll) and its toolchain
# matches cupy 13.4.1's bundled headers; the 12.9.x wheels ship a
# mismatched NVRTC/builtins combination and fail to compile cupy
# kernels in clean environments.  The engine primes the pair by
# absolute path so machine-level PATH pollution (system toolkits,
# conda) cannot hijack it.
& $PY -m pip install -r "$PSScriptRoot\requirements-gpu.txt"

if ($LASTEXITCODE -ne 0) { Write-Error "pip install failed"; exit 1 }

# Verification: every import the app and engine need must succeed.
& $PY -c "import numpy, scipy, pydicom, nibabel, tifffile, PIL, matplotlib, skimage; from PySide6 import QtCore; print('cleanCT deps OK:', numpy.__version__, scipy.__version__, pydicom.__version__, nibabel.__version__, tifffile.__version__)"
if ($LASTEXITCODE -ne 0) { Write-Error "dependency verification failed"; exit 1 }

Write-Host "== done =="
exit 0
