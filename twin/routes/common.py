"""Shared StarterPack context for all routers (one instance per process)."""
from nmr_twin.context import load_context

ctx = load_context()
