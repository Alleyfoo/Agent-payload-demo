"""Tests for the deterministic keys-vs-paste comparison."""

from __future__ import annotations

from agent_network_demo.key_vs_paste import compare


def test_keys_never_drift_any_pass_count():
    m = compare(max_passes=1000)
    for s in m["series"]:
        assert s["keys_errors"] == 0
        assert s["keys_content_bytes"] == 0  # references only, never content
    assert m["endpoint"]["keys_errors"] == 0


def test_keys_do_ship_reference_bytes():
    # Keys aren't free of *any* bytes — the references themselves move. But
    # content bytes stay zero; that is the structural difference.
    m = compare(max_passes=1000)
    assert m["endpoint"]["keys_ref_bytes"] > 0
    assert m["endpoint"]["keys_content_bytes"] == 0


def test_paste_ships_content_every_pass():
    m = compare(max_passes=1000)
    # paste ships at least base_table * N content bytes
    assert m["endpoint"]["paste_content_bytes"] >= m["base_content_bytes"] * 1000
    assert m["base_content_bytes"] > 0


def test_paste_reversible_stays_zero_errors():
    m = compare(max_passes=1000)
    for s in m["series"]:
        assert s["paste_reversible_errors"] == 0
    # ...but it still shipped the whole table each pass:
    assert m["endpoint"]["paste_content_bytes"] > 0


def test_paste_lossy_errors_grow_with_passes():
    m = compare(max_passes=1000)
    s = m["series"]
    assert s[-1]["paste_lossy_errors"] > s[0]["paste_lossy_errors"]
    # linear in passes: str_cells per pass
    assert m["endpoint"]["paste_lossy_errors"] == m["string_cells"] * 1000
    assert m["string_cells"] > 0


def test_paste_lossy_bytes_bloat_more_than_reversible():
    m = compare(max_passes=1000)
    # accumulated padding makes the lossy case ship more than base*N
    assert m["endpoint"]["paste_content_bytes"] > m["base_content_bytes"] * 1000