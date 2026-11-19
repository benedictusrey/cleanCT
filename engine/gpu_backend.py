#!/usr/bin/env python
"""Adaptive, validated CUDA acceleration for the metal-remover pipeline.

The backend prefers PyTorch CUDA, then a separately preflighted CuPy runtime,
and finally NumPy/SciPy. Merely seeing a GPU is not enough: the selected
framework must execute the transfer, comparison, reduction, and float64-mean
operations used by this pipeline before it is marked active.

No GPU model, Python version, CUDA installation, or user-profile path is
hard-coded. Framework-visible CUDA indices respect ``CUDA_VISIBLE_DEVICES``.
"""
from __future__ import annotations

import json
import os
import site
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class GpuInfo:
    available: bool
    backend: str = "cpu"
    device_index: int | None = None
    name: str = ""
    compute_capability: str = ""
    sm_count: int = 0
    total_mem_gb: float = 0.0
    free_mem_gb: float = 0.0
    reason: str = ""


def _torch_candidate(device_index: int | None = None):
    """Return ``(torch, index, GpuInfo)`` after an operational CUDA test."""
    try:
        import torch
        if not torch.cuda.is_available() or torch.cuda.device_count() < 1:
            raise RuntimeError("PyTorch reports no usable CUDA device")
        indices = ([device_index] if device_index is not None
                   else list(range(torch.cuda.device_count())))
        if any(i is None or i < 0 or i >= torch.cuda.device_count()
               for i in indices):
            raise ValueError(f"CUDA device index {device_index} is unavailable")

        observations = []
        for i in indices:
            with torch.cuda.device(i):
                free, total = torch.cuda.mem_get_info(i)
                observations.append((int(free), int(total), int(i)))
        free, total, index = max(observations)
        dev = torch.device(f"cuda:{index}")

        # Exercise every CUDA primitive used by the detector. This catches
        # driver/framework incompatibility without allocating a large buffer.
        x = torch.as_tensor(np.array([[-1000, -500], [1, 4]], np.float32),
                            device=dev)
        count = int((x > 0).sum(dtype=torch.int64).cpu().item())
        mean = float(x.mean(dtype=torch.float64).cpu().item())
        torch.cuda.synchronize(index)
        if count != 2 or abs(mean + 373.75) > 1e-12:
            raise RuntimeError("PyTorch CUDA operational test returned wrong values")

        p = torch.cuda.get_device_properties(index)
        major = int(getattr(p, "major", 0))
        minor = int(getattr(p, "minor", 0))
        info = GpuInfo(
            True, backend="torch", device_index=index, name=str(p.name),
            compute_capability=f"{major}.{minor}",
            sm_count=int(getattr(p, "multi_processor_count", 0)),
            total_mem_gb=round(total / 2**30, 1),
            free_mem_gb=round(free / 2**30, 1),
        )
        return torch, index, info
    except Exception as exc:
        return None, None, GpuInfo(
            False, reason=f"PyTorch CUDA unavailable: {type(exc).__name__}: {exc}")


def _nvrtc_candidate_dirs() -> list[Path]:
    """Find conventional NVRTC wheel/toolkit directories without recursion."""
    roots: list[Path] = []
    try:
        roots.extend(Path(p) for p in site.getsitepackages())
        roots.append(Path(site.getusersitepackages()))
    except Exception:
        pass
    roots.extend([Path(sys.prefix) / "Lib" / "site-packages",
                  Path(sys.prefix) / "Library" / "bin"])
    for key in ("CUDA_PATH", "CUDA_HOME"):
        value = os.environ.get(key)
        if value:
            roots.append(Path(value) / "bin")

    out: list[Path] = []
    for root in roots:
        for candidate in (root, root / "nvidia" / "cuda_nvrtc" / "bin"):
            try:
                if candidate.is_dir() and candidate not in out:
                    out.append(candidate)
            except OSError:
                continue
    return out


def _nvrtc_prime_dirs() -> list[Path]:
    """Directories that may hold the pip 'nvidia-cuda-nvrtc-cu12' wheel's
    NVRTC binaries (deployment infra; wheel layout, not detection logic)."""
    out: list[Path] = []
    try:
        out.extend(Path(p) for p in site.getsitepackages())
        out.append(Path(site.getusersitepackages()))
    except Exception:
        pass
    try:
        out.append(Path(sys.prefix) / "Lib" / "site-packages")
        out.append(Path(sys.prefix))
    except Exception:
        pass
    seen: list[Path] = []
    for root in out:
        for cand in (root / "nvidia" / "cuda_nvrtc" / "bin", root):
            try:
                if cand.is_dir() and cand not in seen:
                    seen.append(cand)
            except OSError:
                continue
    return seen


def _prime_nvrtc_windows() -> str:
    """Windows DLL-order isolation (deployment infra): NVRTC loads its
    'nvrtc-builtins64_*.dll' dependency through the standard loader search,
    which PATH pollution (system toolkits, conda's Library\\bin) can break
    with a mismatched copy.  Preloading the wheel's OWN builtins by absolute
    path makes it resident, so the name-based import inside NVRTC resolves
    to the matching module regardless of PATH.  Returns a diagnostic tag.
    """
    if os.name != "nt":
        return ""
    import ctypes
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except Exception:
        return ""
    for d in _nvrtc_prime_dirs():
        try:
            builtins = sorted(d.glob("nvrtc-builtins64_*.dll"))
            if not builtins:
                continue
            loaded = 0
            for dll in [*builtins,           # builtins FIRST: no further deps
                        d / "nvrtc64_120_0.alt.dll",
                        d / "nvrtc64_120_0.dll"]:
                if dll.is_file() and k32.LoadLibraryW(str(dll)):
                    loaded += 1
            if loaded:
                return f"nvrtc primed from {d}"
        except Exception:
            continue
    return ""


_CUPY_PROBE = r"""
import json, os, numpy as np
if os.name == 'nt':
    _dir = os.environ.get('METAL_REMOVER_NVRTC_DIR')
    if _dir:
        import ctypes, glob
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        for _p in sorted(glob.glob(os.path.join(_dir, 'nvrtc-builtins64_*.dll'))) \
                + [os.path.join(_dir, 'nvrtc64_120_0.alt.dll'),
                   os.path.join(_dir, 'nvrtc64_120_0.dll')]:
            if os.path.isfile(_p):
                k32.LoadLibraryW(_p)
import cupy as cp
n = cp.cuda.runtime.getDeviceCount()
if n < 1:
    raise RuntimeError('no CUDA device')
i = int(__import__('os').environ.get('METAL_REMOVER_CUDA_INDEX', '0'))
with cp.cuda.Device(i):
    x = cp.asarray(np.array([[-1000, -500], [1, 4]], np.float32))
    count = int((x > 0).sum(dtype=cp.int64).get())
    mean = float(x.mean(dtype=cp.float64).get())
    cp.cuda.runtime.deviceSynchronize()
    if count != 2 or abs(mean + 373.75) > 1e-12:
        raise RuntimeError('incorrect CUDA result')
    p = cp.cuda.runtime.getDeviceProperties(i)
    free, total = cp.cuda.runtime.memGetInfo()
    name = p['name'].decode() if isinstance(p['name'], bytes) else str(p['name'])
    print(json.dumps({'index': i, 'name': name,
      'major': int(p['major']), 'minor': int(p['minor']),
      'sms': int(p['multiProcessorCount']), 'free': int(free),
      'total': int(total)}))
"""


def _cupy_candidate(device_index: int | None = None):
    """Preflight CuPy out of process so a broken NVRTC cannot hang the job."""
    index = 0 if device_index is None else int(device_index)
    prime_note = _prime_nvrtc_windows()
    attempts: list[Path | None] = [None, *_nvrtc_candidate_dirs()]
    errors: list[str] = []
    nvrtc_wheel_dir = next((d for d in _nvrtc_prime_dirs()
                            if list(d.glob("nvrtc-builtins64_*.dll"))), None)
    for nvrtc_dir in attempts:
        env = os.environ.copy()
        env["METAL_REMOVER_CUDA_INDEX"] = str(index)
        if nvrtc_wheel_dir is not None:
            env["METAL_REMOVER_NVRTC_DIR"] = str(nvrtc_wheel_dir)
        if nvrtc_dir is not None:
            env["PATH"] = str(nvrtc_dir) + os.pathsep + env.get("PATH", "")
        try:
            proc = subprocess.run(
                [sys.executable, "-c", _CUPY_PROBE], env=env,
                capture_output=True, text=True, timeout=15, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if proc.returncode != 0:
                errors.append(f"probe exit {proc.returncode}")
                continue
            obs = json.loads(proc.stdout.strip().splitlines()[-1])
            if nvrtc_dir is not None:
                os.environ["PATH"] = (str(nvrtc_dir) + os.pathsep
                                      + os.environ.get("PATH", ""))
                if os.name == "nt":
                    os.add_dll_directory(str(nvrtc_dir))
            import cupy as cp
            cp.cuda.Device(index).use()
            info = GpuInfo(
                True, backend="cupy", device_index=index, name=obs["name"],
                compute_capability=f"{obs['major']}.{obs['minor']}",
                sm_count=obs["sms"], total_mem_gb=round(obs["total"] / 2**30, 1),
                free_mem_gb=round(obs["free"] / 2**30, 1),
            )
            return cp, index, info
        except subprocess.TimeoutExpired:
            errors.append("probe timeout")
        except Exception as exc:
            errors.append(type(exc).__name__)
    detail = ", ".join(dict.fromkeys(errors)) or "CuPy not installed"
    return None, None, GpuInfo(False, reason=f"CuPy CUDA unavailable: {detail}")


class GpuBackend:
    """Small framework-neutral API used by the processing pipeline."""

    def __init__(self, preference: str = "auto", device_index: int | None = None,
                 verbose: bool = True) -> None:
        if preference not in {"auto", "torch", "cupy", "cpu"}:
            raise ValueError(f"unknown backend preference: {preference}")
        self.framework = None
        self.device = None
        reasons: list[str] = []

        if preference in {"auto", "torch"}:
            fw, index, info = _torch_candidate(device_index)
            if info.available:
                self.framework = fw
                self.device = fw.device(f"cuda:{index}")
                self.info = info
            else:
                reasons.append(info.reason)
                self.info = info
        else:
            self.info = GpuInfo(False)

        if self.framework is None and preference in {"auto", "cupy"}:
            fw, index, info = _cupy_candidate(device_index)
            if info.available:
                self.framework = fw
                self.device = index
                self.info = info
            else:
                reasons.append(info.reason)
                self.info = info

        if preference == "cpu" or self.framework is None:
            reason = "forced by --cpu" if preference == "cpu" else "; ".join(reasons)
            self.info = GpuInfo(False, reason=reason or "no usable CUDA framework")
        elif self.info.available:
            _prime_nvrtc_windows()   # idempotent; keeps JIT NVRTC intact

        if verbose:
            if self.active:
                print(f"[gpu] {self.info.name} via {self.info.backend} "
                      f"(CUDA:{self.info.device_index}, CC {self.info.compute_capability}, "
                      f"{self.info.free_mem_gb:.1f}/{self.info.total_mem_gb:.1f} GB free) "
                      "- acceleration ACTIVE")
            else:
                print(f"[gpu] CPU mode ({self.info.reason})")

    @property
    def active(self) -> bool:
        return self.framework is not None

    @property
    def backend(self) -> str:
        return self.info.backend if self.active else "cpu"

    def disable(self, reason: str) -> None:
        """Switch to CPU for the rest of the run after a CuPy failure."""
        if self.active:
            print(f"[gpu] GPU failed: {reason}; continuing on CPU", flush=True)
        self.framework = None
        self.info = GpuInfo(False, reason=reason)

    def to_gpu(self, arr: np.ndarray):
        if self.backend == "torch":
            return self.framework.as_tensor(arr, device=self.device)
        if self.backend == "cupy":
            return self.framework.asarray(arr)
        return arr

    def to_cpu(self, arr):
        if isinstance(arr, np.ndarray):
            return arr
        if self.backend == "torch":
            return arr.detach().cpu().numpy()
        if self.backend == "cupy":
            return self.framework.asnumpy(arr)
        return np.asarray(arr)

    def empty_like(self, shape, dtype=np.float32):
        if self.backend == "torch":
            tdtype = self.framework.float32 if np.dtype(dtype) == np.float32 \
                else self.framework.float64
            return self.framework.empty(shape, dtype=tdtype, device=self.device)
        if self.backend == "cupy":
            return self.framework.empty(shape, dtype=dtype)
        return np.empty(shape, dtype=dtype)

    def put_rescaled_slice(self, out, index: int, raw: np.ndarray,
                           slope: float, intercept: float) -> None:
        """Transfer and rescale one slice using explicit float32 arithmetic."""
        s = np.float32(slope)
        b = np.float32(intercept)
        if self.backend == "torch":
            # DICOM ``frombuffer`` arrays are read-only; tensor() performs the
            # required owned copy and avoids undefined writeability semantics.
            x = self.framework.tensor(raw, device=self.device,
                                      dtype=self.framework.float32)
            out[index].copy_(x.mul(s.item()).add(b.item()))
        elif self.backend == "cupy":
            out[index] = self.framework.asarray(raw).astype(
                self.framework.float32) * s + b
        else:
            out[index] = raw.astype(np.float32) * s + b

    def sync(self) -> None:
        if self.backend == "torch":
            self.framework.cuda.synchronize(self.info.device_index)
        elif self.backend == "cupy":
            self.framework.cuda.runtime.deviceSynchronize()

    def release(self) -> None:
        if self.backend == "torch":
            self.framework.cuda.empty_cache()
        elif self.backend == "cupy":
            self.framework.get_default_memory_pool().free_all_blocks()

    def metal_counts(self, vol, thr: float) -> np.ndarray:
        if self.backend == "torch":
            return ((vol > float(thr)).sum(dim=(1, 2), dtype=self.framework.int64)
                    .cpu().numpy())
        if self.backend == "cupy":
            cp = self.framework
            return cp.asnumpy((vol > cp.float32(thr)).sum(
                axis=(1, 2), dtype=cp.int64))
        return (vol > thr).sum(axis=(1, 2), dtype=np.int64)

    def bottom_rows_mean(self, vol, r0: int) -> np.ndarray:
        # float64 accumulation protects the cut decision near its HU threshold.
        if self.backend == "torch":
            return (vol[:, r0:, :].mean(dim=(1, 2), dtype=self.framework.float64)
                    .cpu().numpy())
        if self.backend == "cupy":
            cp = self.framework
            return cp.asnumpy(vol[:, r0:, :].mean(
                axis=(1, 2), dtype=cp.float64))
        return vol[:, r0:, :].mean(axis=(1, 2), dtype=np.float64)

    # ROI morphology remains on SciPy for the Torch backend. These masks are
    # one 2-D slice at a time; keeping them on CPU avoids transfer/JIT overhead.
    def label_slice(self, mask):
        if self.backend == "cupy":
            import cupyx.scipy.ndimage as cndi
            cross = self.framework.asarray(_CROSS_BOOL)
            return cndi.label(self.to_gpu(mask), structure=cross)
        from scipy import ndimage as ndi
        return ndi.label(self.to_cpu(mask),
                         structure=ndi.generate_binary_structure(2, 1))

    def _morph(self, operation: str, mask, iterations: int = 1):
        if self.backend == "cupy":
            import cupyx.scipy.ndimage as cndi
            fn = getattr(cndi, operation)
            # CuPy's multi-iteration morphology only implements the
            # brute-force mode; SciPy's default mode raises
            # NotImplementedError for iterations > 1. Keep the same 4-neighbor
            # footprint as the CPU path and request the supported algorithm.
            return fn(self.to_gpu(mask),
                      structure=self.framework.asarray(_CROSS_BOOL),
                      iterations=iterations, brute_force=True)
        from scipy import ndimage as ndi
        fn = getattr(ndi, operation)
        return fn(self.to_cpu(mask), structure=_CROSS_BOOL,
                  iterations=iterations)

    def binary_erosion(self, mask, iterations: int = 1):
        return self._morph("binary_erosion", mask, iterations)

    def binary_dilation(self, mask, iterations: int = 1):
        return self._morph("binary_dilation", mask, iterations)

    def binary_opening(self, mask, iterations: int = 1):
        return self._morph("binary_opening", mask, iterations)

    def binary_closing(self, mask, iterations: int = 1):
        return self._morph("binary_closing", mask, iterations)


_CROSS_BOOL = np.array([[False, True, False],
                        [True, True, True],
                        [False, True, False]], dtype=bool)


def run_gpu_or_cpu(gpu, gpu_fn, cpu_fn):
    """Run ``gpu_fn`` when ``gpu`` is an active CuPy backend, else ``cpu_fn``.

    A CuPy failure (NVRTC compile error, out of memory, ...) disables the
    backend for the rest of the run and returns ``cpu_fn()`` for this step,
    so one bad kernel no longer fails the whole specimen."""
    if gpu is None or getattr(gpu, "backend", "cpu") != "cupy":
        return cpu_fn()
    try:
        return gpu_fn()
    except Exception as exc:
        gpu.disable(f"{type(exc).__name__}: {exc}")
        return cpu_fn()


def get_backend(verbose: bool = False, preference: str = "auto",
                device_index: int | None = None) -> GpuBackend:
    """Create a validated backend for this run."""
    return GpuBackend(preference=preference, device_index=device_index,
                      verbose=verbose)
