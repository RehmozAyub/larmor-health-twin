"""Reads the raw StarterPack files (NIfTI-1, NIfTI-MRS) with numpy only, for the image and spectrum views.

Spectroscopy convention (StarterPack README): spectrum = fftshift(FFT(fid)); frequency increases with the point
index; ppm = 4.65 + f / nu0. Plotted with ppm decreasing to the right (NMR convention).
"""
from __future__ import annotations

import gzip
import json
import struct
from functools import lru_cache
from pathlib import Path

import numpy as np

from .context import PackContext

DTYPES = {2: np.uint8, 4: np.int16, 8: np.int32, 16: np.float32, 64: np.float64, 32: np.complex64, 1792: np.complex128}
MRS = "04_MRS_BIDS/sub-01/{ses}/mrs/sub-01_{ses}_acq-press_nuc-1H_voi-frontal_svs.nii.gz"
T1W = "03_BIDS_MRI/sub-01/{ses}/anat/sub-01_{ses}_T1w.nii.gz"
ROI = "03_BIDS_MRI/derivatives/roi/sub-01/{ses}/anat/sub-01_{ses}_space-T1w_label-ROI_probseg.nii.gz"
METABOLITES = [("NAA", 2.01), ("Cr", 3.03), ("Cho", 3.20), ("mI", 3.56), ("Glx", 3.75), ("Cr CH2", 3.92)]


@lru_cache(maxsize=32)
def read_nifti(path: str) -> dict:
    b = gzip.open(path).read() if path.endswith(".gz") else Path(path).read_bytes()
    if struct.unpack_from("<i", b, 0)[0] != 348:
        raise ValueError(f"{path}: not a little-endian NIfTI-1 file")
    dim = struct.unpack_from("<8h", b, 40)
    dtype = DTYPES[struct.unpack_from("<h", b, 70)[0]]
    pixdim = struct.unpack_from("<8f", b, 76)
    offset = int(struct.unpack_from("<f", b, 108)[0])
    slope, inter = struct.unpack_from("<2f", b, 112)
    affine = np.array([struct.unpack_from("<4f", b, 280 + 16 * i) for i in range(3)] + [(0, 0, 0, 1)], float)
    shape = tuple(dim[1:1 + dim[0]])
    data = np.frombuffer(b, dtype=dtype, count=int(np.prod(shape)), offset=offset).reshape(shape, order="F")
    if slope not in (0.0, 1.0) and not np.iscomplexobj(data):
        data = data * slope + inter
    ext = None
    if len(b) > 352 and b[348] == 1:
        size, code = struct.unpack_from("<ii", b, 352)
        if code == 44:
            ext = json.loads(b[360:352 + size].rstrip(b"\x00").decode("utf-8"))
    return {"data": np.array(data), "affine": affine, "pixdim": pixdim, "shape": shape, "ext": ext}


def spectrum(ctx: PackContext, session: str, ppm_lo: float = 0.5, ppm_hi: float = 4.3) -> dict:
    n = read_nifti(str(ctx.root / MRS.format(ses=session)))
    fid = n["data"].reshape(-1)
    dwell = float(n["pixdim"][4])
    nu0 = float(n["ext"]["SpectrometerFrequency"][0])
    spec = np.fft.fftshift(np.fft.fft(fid))
    f = np.fft.fftshift(np.fft.fftfreq(fid.size, dwell))
    ppm = 4.65 + f / nu0
    keep = (ppm >= ppm_lo) & (ppm <= ppm_hi)
    real = spec.real[keep]
    noise_win = (ppm >= -3.0) & (ppm <= 0.0)
    naa = (ppm >= 1.9) & (ppm <= 2.1)
    snr = float(spec.real[naa].max() / spec.real[noise_win].std()) if noise_win.any() else None
    fid_show = fid[:420]
    return {"session": session, "ppm": ppm[keep].round(4).tolist(), "real": real.round(3).tolist(),
            "fid_t_ms": (np.arange(fid_show.size) * dwell * 1e3).round(3).tolist(),
            "fid_real": fid_show.real.round(4).tolist(),
            "nu0_MHz": nu0, "dwell_s": dwell, "points": int(fid.size), "snr_recomputed": snr,
            "peaks": [{"name": m, "ppm": p} for m, p in METABOLITES],
            "meta": {k: n["ext"].get(k) for k in ("EchoTime", "RepetitionTime", "PulseSequenceType", "ConversionMethod")},
            "epistemic": "SIMULATED FID → DERIVED spectrum"}


def anatomy(ctx: PackContext, session: str, voi_center_mm=(-16.0, 45.0, 6.0), voi_size_mm=(20, 20, 20)) -> dict:
    """Axial T1w slice through the spectroscopy voxel, the ROI mask on that slice, and the voxel outline."""
    img = read_nifti(str(ctx.root / T1W.format(ses=session)))
    roi = read_nifti(str(ctx.root / ROI.format(ses=session)))
    A = img["affine"]
    inv = np.linalg.inv(A)
    c = inv @ np.array([*voi_center_mm, 1.0])
    k = int(round(c[2]))
    sl = img["data"][:, :, k].astype(float)
    lo, hi = np.percentile(sl, [1, 99.5])
    g = np.clip((sl - lo) / (hi - lo + 1e-9), 0, 1)
    half = np.array(voi_size_mm, float) / 2
    corners = [inv @ np.array([voi_center_mm[0] + sx * half[0], voi_center_mm[1] + sy * half[1], voi_center_mm[2], 1.0])
               for sx, sy in ((-1, -1), (1, 1))]
    vx = sorted([corners[0][0], corners[1][0]]); vy = sorted([corners[0][1], corners[1][1]])
    voxel_mm3 = float(abs(np.linalg.det(A[:3, :3])))
    roi_vol = float(roi["data"].sum() * voxel_mm3)
    return {"session": session, "slice_index": k, "slice_z_mm": float((A @ np.array([0, 0, k, 1.0]))[2]),
            "nx": int(sl.shape[0]), "ny": int(sl.shape[1]), "pixel_mm": [float(A[0, 0]), float(A[1, 1])],
            "image": (g * 255).astype(np.uint8).T.tolist(),          # rows = y, cols = x
            "roi": roi["data"][:, :, k].astype(float).round(2).T.tolist(),
            "voi_px": {"x0": float(vx[0]), "x1": float(vx[1]), "y0": float(vy[0]), "y1": float(vy[1])},
            "roi_volume_mm3_recomputed": round(roi_vol, 1),
            "epistemic": "SIMULATED image; ROI volume DERIVED (sum of partial-volume fractions x voxel volume)"}
