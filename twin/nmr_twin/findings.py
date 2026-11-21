"""A Finding is one checked fact about a packet: what was checked, the result, and which track owns it."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

RANK = {"PASS": 0, "INFO": 0, "WARN": 1, "FAIL": 2}
OWNERS = {"QE": "Quantum Engineering", "PM": "Precision Mechanics / Metrology", "DS": "Data Science",
          "DT": "Digital Twins", "Shared": "Shared gate"}
# The order in which the checker works through a packet (also the order shown in the UI).
LAYERS = ["parse", "schema", "semantic", "linkage", "physics", "policy"]
LAYER_TITLES = {
    "parse": "Can the file be read?",
    "schema": "Are all required fields there, with the right types?",
    "semantic": "Do the values make sense?",
    "linkage": "Is it linked to a known subject, session and source file?",
    "physics": "Is the measurement good enough to compare (physics + metrology)?",
    "policy": "May the twin use it?",
}


@dataclass
class Finding:
    layer: str          # one of LAYERS
    check: str          # short machine name, e.g. "mrs_snr"
    status: str         # PASS / INFO / WARN / FAIL
    owner: str          # QE / PM / DS / DT / Shared
    message: str        # plain-language reason
    value: Any = None
    threshold: str | None = None
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def worst(statuses) -> str:
    """Worst status of an iterable; INFO counts as PASS. Empty -> PASS."""
    result = "PASS"
    for s in statuses:
        s = s if isinstance(s, str) else None   # a status that is not text counts as the worst case
        if RANK.get(s, 2) > RANK[result]:
            result = "FAIL" if RANK.get(s, 2) == 2 else s
    return result
