"""3D scene for the "Where does the evidence come from?" view. Every visible structure comes from a StarterPack file.

Coordinates are scanner millimetres, RAS (x to the subject's Right, y Anterior, z Superior), taken from each file's
own affine (the NIfTI sform). What is built here:

* the T1-weighted volume of each session that has an image file (64 x 64 x 16 voxels of 3 x 3 x 4 mm), sent as raw
  8-bit samples; the browser ray-marches it on the GPU;
* tissue intensity bands found in the data itself (1-D k-means on the in-brain T1w values), so the colours of the
  volume rendering are a documented thresholding of the image, not painted anatomy;
* the brain mask as one iso-contour per acquired slice (16 slices, 4 mm apart), drawn at that slice's real height;
* the acquisition slab (field of view) from the affine and the array shape;
* region-mask isosurfaces for each session that has a mask file (lightly smoothed, marching cubes at 0.5);
* spectroscopy voxel cubes come from the packets themselves (spatial_reference), see `voi_cube`.

Only numpy, scipy and scikit-image. Arrays travel as base64 little-endian binary; the scene stays well under 1.5 MB.
"""
from __future__ import annotations

import base64
import json
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy import ndimage
from skimage import measure

from .context import PackContext
from .imaging import ROI, T1W, read_nifti

BRAIN_MASK = "02_NIfTI/synthetic_brain_mask.nii.gz"
TISSUE_NAMES = ("CSF", "Lesion", "Grey matter", "White matter")     # k-means bands, darkest to brightest on T1w
TISSUE_NOTES = (
    "Fluid spaces. Darkest on a T1-weighted image.",
    "Darker spot that lies entirely inside the region mask.",
    "Outer tissue band.",
    "Inner tissue band. Brightest on a T1-weighted image.",
)


# ---------------------------------------------------------------- geometry helpers

def _ijk_to_mm(ijk: np.ndarray, affine: np.ndarray) -> np.ndarray:
    return ijk @ affine[:3, :3].T + affine[:3, 3]


def _signed_volume(vertices: np.ndarray, faces: np.ndarray) -> float:
    a, b, c = (vertices[faces[:, i]] for i in range(3))
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def enclosed_volume(vertices: np.ndarray, faces: np.ndarray) -> float:
    """Volume inside a closed triangle mesh (divergence theorem), in mm3."""
    return abs(_signed_volume(vertices, faces))


def _surface(vol: np.ndarray, affine: np.ndarray, sigma_mm: float, upsample: float) -> dict:
    """Isosurface of a 0..1 volume at level 0.5, in scanner mm, triangles counter-clockwise seen from outside."""
    vox = np.sqrt((affine[:3, :3] ** 2).sum(axis=0))                 # voxel size per array axis, mm
    v = ndimage.gaussian_filter(vol.astype(np.float64), sigma=sigma_mm / vox, mode="constant")
    v = np.pad(v, 1)                                                  # closed surface even at the volume edge
    scale = np.ones(3)
    if upsample != 1:
        z = ndimage.zoom(v, upsample, order=1)
        scale = (np.array(v.shape) - 1) / (np.array(z.shape) - 1)
        v = z
    verts, faces, _, _ = measure.marching_cubes(v, level=0.5)
    mm = _ijk_to_mm(verts * scale - 1.0, affine)
    faces = faces.astype(np.int64)
    if _signed_volume(mm, faces) < 0:
        faces = faces[:, ::-1].copy()
    return {"vertices": mm, "faces": faces}


def slab_bounds(affine: np.ndarray, shape) -> np.ndarray:
    """Field of view: the outer faces of the first and last voxels, as [[xmin, ymin, zmin], [xmax, ymax, zmax]]."""
    n = np.array(shape[:3], float)
    corners = np.array([[i, j, k] for i in (-0.5, n[0] - 0.5) for j in (-0.5, n[1] - 0.5) for k in (-0.5, n[2] - 0.5)])
    mm = _ijk_to_mm(corners, affine)
    return np.array([mm.min(0), mm.max(0)])


def slice_contours(mask: np.ndarray, affine: np.ndarray, smooth_px: float = 0.6) -> list[dict]:
    """One entry per acquired slice: the brain-mask outline(s) on that slice, in mm, at the slice centre height."""
    out = []
    for k in range(mask.shape[2]):
        sl = ndimage.gaussian_filter(mask[:, :, k].astype(float), smooth_px)
        rings = []
        if sl.max() > 0.5:
            for c in measure.find_contours(np.pad(sl, 1), 0.5):
                c = measure.approximate_polygon(c - 1.0, tolerance=0.15)
                ijk = np.column_stack([c, np.full(len(c), k)])
                rings.append(np.round(_ijk_to_mm(ijk, affine), 2))
        z = float(_ijk_to_mm(np.array([[0, 0, k]]), affine)[0, 2])
        out.append({"k": k, "z_mm": z, "rings": rings})
    return out


def cube_corners(center, size) -> np.ndarray:
    """The 8 corners of an axis-aligned box, ordered by (x, y, z) bits."""
    c, h = np.asarray(center, float), np.asarray(size, float) / 2
    return np.array([c + h * np.array([sx, sy, sz]) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)])


def voi_cube(spatial_reference: dict, observable: str = "") -> dict | None:
    """Spectroscopy voxel stated by a packet. Choline packets are drawn shifted by the packet's own
    chemical-shift displacement (csde_mm_NAA_Cho, per axis); the sign is a drawing convention."""
    sr = spatial_reference or {}
    if "voi_center_mm" not in sr:
        return None
    c = np.array(sr["voi_center_mm"], float)
    s = np.array(sr.get("voi_size_mm", (20, 20, 20)), float)
    shift = np.full(3, float(sr.get("csde_mm_NAA_Cho", 0.0))) if observable.lower().startswith("cho") else np.zeros(3)
    return {"center": c + shift, "size": s, "corners": cube_corners(c + shift, s), "shift_mm": shift}


def tissue_bands(values: np.ndarray, k: int = 4, iters: int = 60) -> dict:
    """1-D k-means on in-brain T1w values: band centres, boundaries (midpoints) and voxel counts."""
    v = np.sort(values.astype(float))
    c = np.linspace(v[0], v[-1], k)                                  # spread over the range, not quantiles
    for _ in range(iters):
        lab = np.argmin(np.abs(v[:, None] - c[None, :]), axis=1)
        new = np.array([v[lab == i].mean() if np.any(lab == i) else c[i] for i in range(k)])
        if np.allclose(new, c):
            break
        c = new
    order = np.argsort(c)
    c = c[order]
    lab = np.argmin(np.abs(v[:, None] - c[None, :]), axis=1)
    return {"centres": c, "bounds": (c[:-1] + c[1:]) / 2, "counts": np.bincount(lab, minlength=k)}


# ---------------------------------------------------------------- the scene

def image_sessions(root: Path) -> list[str]:
    """Sessions that have a T1-weighted image file in the StarterPack."""
    return sorted(p.name for p in (root / "03_BIDS_MRI" / "sub-01").glob("ses-*")
                  if (root / T1W.format(ses=p.name)).exists())


@lru_cache(maxsize=2)
def build_scene(root: str) -> dict:
    """All geometry and volumes as numpy arrays (used by the tests and by the web payload)."""
    r = Path(root)
    brain = read_nifti(str(r / BRAIN_MASK))
    mask = brain["data"] > 0
    out = {"affine": brain["affine"], "shape": brain["shape"], "slab": slab_bounds(brain["affine"], brain["shape"]),
           "contours": slice_contours(mask, brain["affine"]), "sessions": {},
           # the brain mask as a smooth closed surface (drawn as glass); flat top and bottom = edge of the scanned slab
           "brain_surface": _surface(mask.astype(float), brain["affine"], sigma_mm=2.5, upsample=1.5)}
    vmax = 0.0
    for ses in image_sessions(r):
        t1 = read_nifti(str(r / T1W.format(ses=ses)))
        entry = {"t1w": t1["data"].astype(np.float64), "affine": t1["affine"], "t1w_file": T1W.format(ses=ses)}
        vmax = max(vmax, float(entry["t1w"].max()))
        roi_path = r / ROI.format(ses=ses)
        if roi_path.exists():
            n = read_nifti(str(roi_path))
            p = np.clip(n["data"], 0, 1)
            entry.update(roi=p, roi_file=ROI.format(ses=ses),
                         roi_surface=_surface(p, n["affine"], sigma_mm=1.5, upsample=2.0),
                         roi_volume_mm3=float(p.sum() * abs(np.linalg.det(n["affine"][:3, :3]))))
        out["sessions"][ses] = entry
    out["vmax"] = vmax
    ref = out["sessions"][image_sessions(r)[0]]["t1w"]
    out["bands"] = tissue_bands(ref[mask])
    return out


def _b64(a: np.ndarray, dtype) -> str:
    return base64.b64encode(np.ascontiguousarray(a, dtype=np.dtype(dtype).newbyteorder("<")).tobytes()).decode("ascii")


def _u8_volume(a: np.ndarray, scale: float) -> str:
    """Volume as 8-bit samples in x-fastest order (i + 64 j + 64*64 k), the layout of a WebGL 3D texture."""
    q = np.clip(np.round(a * scale), 0, 255).astype(np.uint8)
    return _b64(q.reshape(-1, order="F"), "uint8")


def _mesh_payload(m: dict) -> dict:
    v, f = m["vertices"], m["faces"]
    idx_t = "uint16" if len(v) < 65536 else "uint32"
    return {"n_vertices": int(len(v)), "n_faces": int(len(f)),
            "positions": _b64(np.round(v, 2), "float32"), "indices": _b64(f.reshape(-1), idx_t), "index_type": idx_t,
            "surface_volume_mm3": round(enclosed_volume(v, f), 1),
            "bbox_mm": [np.round(v.min(0), 2).tolist(), np.round(v.max(0), 2).tolist()]}


def scene(ctx: PackContext) -> dict:
    """JSON-ready scene for GET /api/scene."""
    g = build_scene(str(ctx.root))
    scale = 255.0 / g["vmax"]
    b = g["bands"]
    sessions = {}
    for ses, e in g["sessions"].items():
        sessions[ses] = {
            "t1w": _u8_volume(e["t1w"], scale), "t1w_file": e["t1w_file"],
            "roi": _u8_volume(e["roi"], 255.0) if "roi" in e else None,
            "roi_file": e.get("roi_file"),
            "roi_surface": _mesh_payload(e["roi_surface"]) if "roi_surface" in e else None,
            "roi_volume_mm3": round(e["roi_volume_mm3"], 1) if "roi_volume_mm3" in e else None,
        }
    base = sessions.get("ses-baseline", {}).get("roi_volume_mm3")
    fol = sessions.get("ses-followup", {}).get("roi_volume_mm3")
    return {
        "frame": "scanner RAS, millimetres (x right, y anterior, z superior)",
        "epistemic": "SIMULATED volumes; DERIVED surfaces, contours and intensity bands",
        "affine": np.round(g["affine"], 4).tolist(),
        "shape": [int(s) for s in g["shape"][:3]],
        "slab_mm": np.round(g["slab"], 3).tolist(),
        "intensity_scale": {"stored_max": g["vmax"], "u8_per_unit": scale},
        "bands": [{"name": n, "note": t, "centre": round(float(c) * scale, 2), "count": int(k)}
                  for n, t, c, k in zip(TISSUE_NAMES, TISSUE_NOTES, b["centres"], b["counts"])],
        "band_bounds_u8": [round(float(x) * scale, 2) for x in b["bounds"]],
        "contours": [{"k": c["k"], "z_mm": c["z_mm"], "rings": [ring[:, :2].tolist() for ring in c["rings"]]}
                     for c in g["contours"]],
        "sessions": sessions,
        "brain_surface": _mesh_payload(g["brain_surface"]),
        "roi_change": {"baseline": base, "followup": fol,
                       "increase_pct": round(100 * (fol / base - 1), 1) if base and fol else None},
    }


def library_geometry(ctx: PackContext, library: list[dict], read) -> list[dict]:
    """Spatial references stated by the library packets (so a rejected packet can still be placed)."""
    out = []
    for item in library:
        try:
            p = json.loads(read(ctx, item["id"]))
        except (ValueError, FileNotFoundError):
            continue
        if not isinstance(p, dict) or not isinstance(p.get("spatial_reference"), dict):
            continue
        sr = p["spatial_reference"]
        if "voi_center_mm" not in sr:
            continue
        out.append({"library_id": item["id"], "packet_id": p.get("packet_id"), "session_id": p.get("session_id"),
                    "observable": p.get("observable"), "spatial_reference": sr})
    return out
