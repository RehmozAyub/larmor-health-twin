"""Provenance: walk back from a twin variable to the source files (W3C PROV idea: entities, activities, agents)."""
from __future__ import annotations

from .context import PackContext, file_sha256
from .twin import Twin


def trace(twin: Twin, name: str, ctx: PackContext) -> dict:
    """Return a graph {nodes, edges} from the variable back to raw files, with live hash verification."""
    nodes, edges = [], []
    var = twin.variables.get(name)
    if var is None:
        return {"nodes": nodes, "edges": edges}
    vid = f"var:{name}"
    nodes.append({"id": vid, "kind": "state", "label": f"{name} = {var.mean:.4g} ± {var.sd:.2g}",
                  "detail": f"twin state v{twin.version}, INFERRED"})
    for ev in [e for e in twin.events if e.get("observable") == name]:
        eid = f"ev:{ev['event_id']}"
        label = f"#{ev['event_id']} {ev['type'].replace('update_with_warning', 'warn update')}"
        if "K" in ev:
            label += f" (K = {ev['K']:.3f})"
        nodes.append({"id": eid, "kind": "activity", "label": label, "detail": ev.get("reason", "")})
        edges.append({"from": eid, "to": vid, "label": "updated" if ev["type"] != "reject" else "rejected"})
        pid = ev.get("packet_id") or "unknown packet"
        pnode = f"pk:{pid}"
        if not any(n["id"] == pnode for n in nodes):
            nodes.append({"id": pnode, "kind": "entity", "label": f"packet {pid}",
                          "detail": f"QC {ev['qc_status']}, origin {ev.get('origin')}, value {ev.get('value_epistemic')}"})
        edges.append({"from": pnode, "to": eid, "label": "used"})
        prov = ev.get("provenance") or {}
        acts = prov.get("activities") or []
        if acts:
            aid = f"proc:{pid}"
            proc = ev.get("processing") or {}
            nodes.append({"id": aid, "kind": "activity", "label": " → ".join(acts),
                          "detail": f"pipeline {proc.get('pipeline')} v{proc.get('version')}"})
            edges.append({"from": aid, "to": pnode, "label": "generated"})
            parent_target = aid
        else:
            parent_target = pnode
        for parent in prov.get("parents") or []:
            fid = f"file:{parent}"
            if not any(n["id"] == fid for n in nodes):
                path = ctx.root / parent
                verified = None
                actual = None
                if path.is_file():
                    actual = file_sha256(path)
                    expected = ctx.manifest.get(parent)
                    verified = (expected == actual) if expected else None
                nodes.append({"id": fid, "kind": "file", "label": parent.split("/")[-1], "path": parent,
                              "sha256": actual, "verified": verified,
                              "detail": "MEASURED-level source (here: SIMULATED origin)"})
            edges.append({"from": fid, "to": parent_target, "label": "input"})
    return {"nodes": nodes, "edges": edges}
