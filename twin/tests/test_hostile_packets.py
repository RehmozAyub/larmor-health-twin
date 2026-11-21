"""Hostile input: whatever a packet contains, the checker answers with a verdict and the twin state stays usable.

Each case here once produced a server error in a stress test (21 Nov). They are the "unseen packet" defence.
"""
import json

import pytest

from nmr_twin import service
from nmr_twin.checker import check_packet
from nmr_twin.twin import Twin


def _packet(ctx, pid="E-t1-cho"):
    return json.loads(service.load_packet_text(ctx, pid))


def _mutated(ctx, pid, path, value):
    p = _packet(ctx, pid)
    node = p
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return p


@pytest.mark.parametrize("text", [
    '{"value": NaN}', '{"value": Infinity}', '{"value": -Infinity}', '{"value": 1e999}',
    "", "null", "[]", "42", '"text"', "{" * 5000, '{"a":' * 5000 + "1" + "}" * 5000,
])
def test_text_that_is_not_a_packet_is_rejected_at_parse(ctx, text):
    v = check_packet(text, ctx, service.golden_path(ctx))
    assert v.action == "reject"
    assert v.findings[0].layer == "parse" and v.findings[0].status == "FAIL"
    json.dumps(v.to_dict(), allow_nan=False)        # the verdict itself must be sendable as strict JSON


def test_nan_anywhere_in_a_real_packet_is_rejected(ctx):
    text = service.load_packet_text(ctx, "E-t1-cho").replace('"value": 0.85', '"value": NaN', 1)
    assert "NaN" in text
    v = check_packet(text, ctx, service.golden_path(ctx, include_followup=False))
    assert v.action == "reject" and v.packet is None


@pytest.mark.parametrize("path,value", [
    (("modality",), []), (("modality",), {}), (("qc_status",), []), (("qc_status",), {}),
    (("value",), 10 ** 400), (("value",), "0.85"), (("value",), [0.85]), (("uncertainty",), 10 ** 400),
    (("qc_checks",), "PASS"), (("qc_checks",), [None, 3, "x"]), (("provenance",), "none"),
    (("relative_time",), 7), (("spatial_reference",), []), (("observable",), {"x": 1}), (("packet_id",), 12),
])
def test_wrong_types_never_raise(ctx, path, value):
    v = check_packet(_mutated(ctx, "E-t1-cho", path, value), ctx, service.golden_path(ctx, include_followup=False))
    assert v.action in ("update", "update_with_warning", "reject")
    json.dumps(v.to_dict()["findings"], allow_nan=False)


def test_zero_region_volume_is_rejected_not_divided_by(ctx):
    v = check_packet(_mutated(ctx, "E-t1-roi", ("value",), 0), ctx, service.golden_path(ctx, include_followup=False))
    assert v.action == "reject"


def test_packet_ids_are_never_paths(ctx):
    for bad in ("..%sstate%stwin_state" % (chr(92), chr(92)), "../state/twin_state", "C:/x", ""):
        with pytest.raises(FileNotFoundError):
            service.read_library_packet(ctx, bad)


def test_broken_state_file_falls_back_instead_of_stopping_the_app(tmp_path):
    for content in ("", "null", "{", '{"subject_id": "sub-01"'):
        f = tmp_path / "twin_state.json"
        f.write_text(content, encoding="utf-8")
        assert Twin.load(f) is None


def test_state_survives_a_save_and_load_round_trip(ctx, tmp_path):
    t = service.golden_path(ctx)
    f = tmp_path / "twin_state.json"
    t.save(f)
    again = Twin.load(f)
    assert again is not None and again.version == t.version
    assert abs(again.variables["Cho_Cr"].mean - t.variables["Cho_Cr"].mean) < 1e-12
