"""Router for the 3D 'Where does the evidence come from?' scene.

GET /api/scene                   T1w volumes, slice contours, acquisition slab, region surfaces (cached in memory)
GET /api/scene/library-geometry  where each library packet says its spectroscopy voxel is (to place rejected packets)
The evidence cubes themselves come from the twin state (GET /api/state), polled by the page.
"""
from __future__ import annotations

import threading

from fastapi import APIRouter

from nmr_twin import mesh
from nmr_twin.service import library, read_library_packet
from routes.common import ctx

router = APIRouter()
_cache: dict = {}
_lock = threading.Lock()


@router.get("/scene")
def get_scene() -> dict:
    """Computed once per process, then served from memory."""
    with _lock:
        if "scene" not in _cache:
            _cache["scene"] = mesh.scene(ctx)
        return _cache["scene"]


@router.get("/scene/library-geometry")
def get_library_geometry() -> list[dict]:
    """Read fresh each time: the library folder can gain packets while the server runs."""
    return mesh.library_geometry(ctx, library(ctx), read_library_packet)
