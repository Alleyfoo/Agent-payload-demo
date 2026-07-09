"""Tests for the capability-scoped StoreView — the mechanism that makes
"passing keys" load-bearing. An agent's view may read only its granted
input_keys and write only its contracted output key; anything else is a
ContractError."""

from __future__ import annotations

import pytest

from agent_network_demo.artifact_store import ArtifactStore
from agent_network_demo.contracts import ContractError


def _store_with_a():
    s = ArtifactStore()
    s.register("artifact.a", {"type": "table_preview", "status": "ok"})
    s.register("artifact.b", {"type": "schema_profile", "status": "ok"})
    return s


def test_get_refuses_ungranted_key():
    s = _store_with_a()
    view = s.view(read_keys=["artifact.a"], write_key="artifact.c")
    # granted key works
    assert view.get("artifact.a")["type"] == "table_preview"
    # present in the store but NOT granted -> denied
    with pytest.raises(ContractError, match="denied"):
        view.get("artifact.b")
    # not present and not granted -> denied (no probing)
    with pytest.raises(ContractError, match="denied"):
        view.get("artifact.never")


def test_has_cannot_probe_ungranted_keys():
    s = _store_with_a()
    view = s.view(read_keys=["artifact.a"], write_key="artifact.c")
    assert view.has("artifact.a") is True
    # artifact.b exists in the store, but the view was not handed it.
    assert view.has("artifact.b") is False
    assert view.has("artifact.missing") is False


def test_register_refuses_wrong_write_key():
    s = _store_with_a()
    view = s.view(read_keys=["artifact.a"], write_key="artifact.schema_profile")
    # contracted write key works
    view.register("artifact.schema_profile",
                  {"type": "schema_profile", "status": "ok", "x": 1})
    assert s.has("artifact.schema_profile")
    # a different key is denied even if it shares the prefix family
    with pytest.raises(ContractError, match="denied"):
        view.register("artifact.cleaned_output",
                      {"type": "cleaned_output", "status": "ok"})


def test_register_refuses_any_write_when_no_contract():
    s = _store_with_a()
    view = s.view(read_keys=["artifact.a"], write_key="")
    with pytest.raises(ContractError, match="no output_contract"):
        view.register("artifact.anything",
                      {"type": "t", "status": "ok"})


def test_view_does_not_leak_store_mutation_surface():
    """The view exposes only get/has/register — no keys(), as_dict(), etc.
    An agent cannot enumerate the store through its view."""
    s = _store_with_a()
    view = s.view(read_keys=["artifact.a"], write_key="artifact.c")
    for attr in ("keys", "as_dict", "summary", "set_status", "to_snapshot"):
        assert not hasattr(view, attr), f"view leaked {attr!r}"


def test_write_key_for_maps_each_contract():
    from agent_network_demo.contracts import write_key_for
    assert write_key_for("table_preview.v1") == "artifact.raw_input"
    assert write_key_for("schema_profile.v1") == "artifact.schema_profile"
    assert write_key_for("cleaned_output.v1") == "artifact.cleaned_output"
    assert write_key_for("validation_verdict.v1") == "artifact.validation_verdict"
    assert write_key_for("") == ""