"""3D scene: volumes, contours, slab and surfaces come from the StarterPack files, in scanner millimetres."""
import base64
import json

import numpy as np
import pytest

from nmr_twin import mesh
from nmr_twin.imaging import ROI, read_nifti
from nmr_twin.service import library, read_library_packet


@pytest.fixture(scope="module")
def geo(ctx):
    return mesh.build_scene(str(ctx.root))


@pytest.fixture(scope="module")
def payload(ctx):
    return mesh.scene(ctx)


def test_slab_bounds_match_the_affine(geo):
    A, shape = geo["affine"], geo["shape"]
    assert tuple(shape[:3]) == (64, 64, 16)
    assert np.allclose(np.sqrt((A[:3, :3] ** 2).sum(0)), [3, 3, 4])            # 3 x 3 x 4 mm voxels
    lo, hi = geo["slab"]
    assert np.allclose(lo, A[:3, 3] - 0.5 * np.array([3, 3, 4]))               # outer face of the first voxel
    assert np.allclose(hi - lo, [192, 192, 64])                                # 64 x 3, 64 x 3, 16 x 4 mm


def test_one_contour_entry_per_acquired_slice(geo):
    c = geo["contours"]
    assert [e["k"] for e in c] == list(range(16))
    assert [e["z_mm"] for e in c] == [-32 + 4 * k for k in range(16)]         # slice centres, 4 mm apart
    with_brain = [e for e in c if e["rings"]]
    assert len(with_brain) == 12                                               # the outer 2 + 2 slices hold no brain
    lo, hi = geo["slab"]
    for e in with_brain:
        for ring in e["rings"]:
            assert len(ring) >= 8 and np.all(ring[:, :2] >= lo[:2]) and np.all(ring[:, :2] <= hi[:2])
            assert np.allclose(ring[:, 2], e["z_mm"])


def test_volume_texture_shape_and_spacing(payload):
    assert payload["shape"] == [64, 64, 16]
    assert np.allclose(np.sqrt((np.array(payload["affine"])[:3, :3] ** 2).sum(0)), [3, 3, 4])
    for ses in ("ses-baseline", "ses-followup"):
        vol = np.frombuffer(base64.b64decode(payload["sessions"][ses]["t1w"]), np.uint8)
        assert vol.size == 64 * 64 * 16 and vol.max() > 200
        roi = np.frombuffer(base64.b64decode(payload["sessions"][ses]["roi"]), np.uint8)
        assert roi.size == vol.size


def test_texture_layout_is_x_fastest(ctx, payload):
    """Sample (i, j, k) of the texture must equal voxel (i, j, k) of the file."""
    t = read_nifti(str(ctx.root / ROI.format(ses="ses-baseline")))["data"]
    roi = np.frombuffer(base64.b64decode(payload["sessions"]["ses-baseline"]["roi"]), np.uint8).reshape(16, 64, 64)
    i, j, k = np.argwhere(t > 0.99)[0]
    assert roi[k, j, i] == 255


def test_tissue_bands_come_from_the_data(geo, ctx):
    b = geo["bands"]
    assert len(b["centres"]) == 4 and np.all(b["counts"] > 100)
    assert np.all(np.diff(b["centres"]) > 50)                                  # four separate intensity bands
    # the second-darkest band (the lesion) lies entirely inside the baseline region mask
    t1 = geo["sessions"]["ses-baseline"]["t1w"]
    roi = geo["sessions"]["ses-baseline"]["roi"]
    lesion = (t1 > b["bounds"][0]) & (t1 < b["bounds"][1])
    assert lesion.sum() > 100 and np.all(roi[lesion] > 0.5)


def test_followup_region_encloses_more_volume(geo):
    s = geo["sessions"]
    vb = mesh.enclosed_volume(s["ses-baseline"]["roi_surface"]["vertices"], s["ses-baseline"]["roi_surface"]["faces"])
    vf = mesh.enclosed_volume(s["ses-followup"]["roi_surface"]["vertices"], s["ses-followup"]["roi_surface"]["faces"])
    assert vf > vb * 1.15
    assert s["ses-baseline"]["roi_volume_mm3"] == pytest.approx(22140, abs=1)
    assert s["ses-followup"]["roi_volume_mm3"] == pytest.approx(27810, abs=1)
    assert vb == pytest.approx(22140, rel=0.08) and vf == pytest.approx(27810, rel=0.08)


def test_packet_voxel_is_inside_the_brain(ctx, geo):
    packet = json.loads(read_library_packet(ctx, "E-t1-cho"))
    naa = mesh.voi_cube(packet["spatial_reference"], "NAA_Cr")
    cho = mesh.voi_cube(packet["spatial_reference"], packet["observable"])
    assert np.allclose(naa["center"], [-16, 45, 6]) and np.allclose(np.ptp(naa["corners"], axis=0), 20)
    assert np.allclose(cho["center"] - naa["center"], 2.4)
    rings = np.vstack([r for e in geo["contours"] for r in e["rings"]])
    lo, hi = rings.min(0), rings.max(0)
    lo[2], hi[2] = geo["slab"][0][2], geo["slab"][1][2]
    for cube in (naa, cho):
        assert np.all(cube["corners"] >= lo) and np.all(cube["corners"] <= hi)


def test_library_geometry_places_rejected_packets(ctx):
    g = mesh.library_geometry(ctx, library(ctx), read_library_packet)
    ids = {x["library_id"] for x in g}
    assert {"E-t0-cho", "E-t1-naa", "U01_repeat_after_reshim_PASS"} <= ids
    assert all(len(x["spatial_reference"]["voi_center_mm"]) == 3 for x in g)


def test_web_payload_is_small_and_decodes(payload, geo):
    assert len(json.dumps(payload)) < 1_500_000
    m = payload["sessions"]["ses-baseline"]["roi_surface"]
    pos = np.frombuffer(base64.b64decode(m["positions"]), dtype="<f4").reshape(-1, 3)
    idx = np.frombuffer(base64.b64decode(m["indices"]), dtype="<u2" if m["index_type"] == "uint16" else "<u4")
    assert pos.shape == (m["n_vertices"], 3) and idx.size == 3 * m["n_faces"]
    assert np.allclose(pos, geo["sessions"]["ses-baseline"]["roi_surface"]["vertices"], atol=0.01)
    assert payload["roi_change"]["increase_pct"] == pytest.approx(25.6, abs=0.1)
