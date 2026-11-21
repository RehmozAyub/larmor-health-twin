"""Loads everything the checker needs from the StarterPack: schema, thresholds, sessions, participants, hashes."""
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from . import config


def _read_tsv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


@lru_cache(maxsize=256)
def sha256_of(path: str, mtime: float) -> str:  # mtime in the key: a changed file is re-hashed
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def file_sha256(path: Path) -> str:
    return sha256_of(str(path), path.stat().st_mtime)


@dataclass
class PackContext:
    root: Path
    schema: dict
    thresholds: dict
    contract: dict
    participants: set[str]
    sessions: dict[str, dict[str, datetime]]          # subject -> session -> acquisition time
    manifest: dict[str, str]                          # relative path -> sha256
    data_dictionary: list[dict] = field(default_factory=list)

    @property
    def gates(self) -> dict[str, dict]:
        return {g["name"]: g for g in self.thresholds.get("gates", [])}

    @property
    def policy(self) -> dict:
        return self.thresholds["twin_policy"]

    def session_time(self, subject: str, session: str) -> datetime | None:
        return self.sessions.get(subject, {}).get(session)

    def months_between(self, subject: str, s0: str, s1: str) -> float | None:
        t0, t1 = self.session_time(subject, s0), self.session_time(subject, s1)
        if t0 is None or t1 is None:
            return None
        return (t1 - t0).total_seconds() / (86400 * 30.4375)

    def register_session(self, subject: str, session: str, acq_time: str) -> None:
        """Team-side registration of a new session (e.g. a repeat scan). Persisted in data/sessions_extra.tsv."""
        when = datetime.fromisoformat(acq_time).replace(tzinfo=None)   # sessions are compared as local wall-clock times
        self.sessions.setdefault(subject, {})[session] = when
        path = config.SESSIONS_EXTRA
        rows = [r for r in _read_tsv(path) if not (r["subject_id"] == subject and r["session_id"] == session)]
        rows.append({"subject_id": subject, "session_id": session, "acq_time": when.isoformat()})
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, ["subject_id", "session_id", "acq_time"], delimiter="\t")
            w.writeheader()
            w.writerows(rows)


def load_context(root: Path | None = None) -> PackContext:
    root = Path(root or config.STARTERPACK)
    tr = root / "05_TwinReady_JSON_CSV"
    schema = json.loads((tr / "evidence_packet_v1.0.schema.json").read_text(encoding="utf-8"))
    thresholds = json.loads((tr / "thresholds-v1.0.json").read_text(encoding="utf-8"))
    contract = json.loads((tr / "data_contract.json").read_text(encoding="utf-8"))

    participants = {r["participant_id"] for r in _read_tsv(root / "03_BIDS_MRI" / "participants.tsv")}
    participants |= {r["participant_id"] for r in _read_tsv(root / "04_MRS_BIDS" / "participants.tsv")}

    sessions: dict[str, dict[str, datetime]] = {}
    for sub in sorted(participants):
        for base in ("03_BIDS_MRI", "04_MRS_BIDS"):
            for r in _read_tsv(root / base / sub / f"{sub}_sessions.tsv"):
                sessions.setdefault(sub, {})[r["session_id"]] = datetime.fromisoformat(r["acq_time"])
    for r in _read_tsv(config.SESSIONS_EXTRA):
        sessions.setdefault(r["subject_id"], {})[r["session_id"]] = datetime.fromisoformat(r["acq_time"])

    manifest = {}
    with open(root / "manifest_sha256.csv", encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            manifest[r["path"]] = r["sha256"]

    with open(tr / "data_dictionary.csv", encoding="utf-8", newline="") as fh:
        dictionary = list(csv.DictReader(fh))

    return PackContext(root=root, schema=schema, thresholds=thresholds, contract=contract,
                       participants=participants, sessions=sessions, manifest=manifest,
                       data_dictionary=dictionary)
