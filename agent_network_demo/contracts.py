"""Contracts: the handoff envelope between agents + the action vocabulary.

The envelope is the *only* thing that passes from one agent to the next,
and it carries **references** (keys into the artifact store), never content.
An agent declares, up front, what it will read (``input_keys``) and what kind
of artifact it promises to produce (``output_contract``). The runner
enforces both before and after the agent runs — so a misbehaving agent cannot
silently read or write the wrong thing.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

# Ensure the package parent (repo root) is on sys.path so the absolute import
# below resolves whether this module is run as a script, imported as a top-level
# module, or imported as part of the agent_network_demo package.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from agent_network_demo.artifact_store import ArtifactStore

# ---------------------------------------------------------------------------
# Action vocabulary — the closed set of things any agent may do.
# Keeping this finite and explicit is the "keys not blobs" security story:
# an agent's powers are declared on the envelope, not invented at runtime.
# ---------------------------------------------------------------------------

ACTION_READ_ARTIFACT = "read_artifact"
ACTION_WRITE_TABLE_PREVIEW = "write_table_preview"
ACTION_WRITE_SCHEMA_PROFILE = "write_schema_profile"
ACTION_WRITE_CLEANED_OUTPUT = "write_cleaned_output"
ACTION_WRITE_VALIDATION_VERDICT = "write_validation_verdict"

ALLOWED_ACTIONS: Set[str] = {
    ACTION_READ_ARTIFACT,
    ACTION_WRITE_TABLE_PREVIEW,
    ACTION_WRITE_SCHEMA_PROFILE,
    ACTION_WRITE_CLEANED_OUTPUT,
    ACTION_WRITE_VALIDATION_VERDICT,
}

# ---------------------------------------------------------------------------
# Output contracts — what kind of artifact an agent promises to produce.
# Used as the *base* of the output key, e.g. contract "schema_profile.v1"
# licenses the agent to write a key under artifact.schema_profile.*.
# ---------------------------------------------------------------------------

CONTRACT_TABLE_PREVIEW = "table_preview.v1"
CONTRACT_SCHEMA_PROFILE = "schema_profile.v1"
CONTRACT_CLEANED_OUTPUT = "cleaned_output.v1"
CONTRACT_VALIDATION_VERDICT = "validation_verdict.v1"

OUTPUT_CONTRACTS: Set[str] = {
    CONTRACT_TABLE_PREVIEW,
    CONTRACT_SCHEMA_PROFILE,
    CONTRACT_CLEANED_OUTPUT,
    CONTRACT_VALIDATION_VERDICT,
}

# Map each output contract to the key prefix an agent writing it may use.
_CONTRACT_PREFIX: Dict[str, str] = {
    CONTRACT_TABLE_PREVIEW: "artifact.raw_input",
    CONTRACT_SCHEMA_PROFILE: "artifact.schema_profile",
    CONTRACT_CLEANED_OUTPUT: "artifact.cleaned_output",
    CONTRACT_VALIDATION_VERDICT: "artifact.validation_verdict",
}

# The write action an envelope MUST be granted for a given output_contract.
# This is what makes ``allowed_actions`` a real grant instead of descriptive
# metadata: the contract the agent promises to fulfil must be backed by the
# matching write permission, including Intake's ``write_table_preview``.
_REQUIRED_ACTION_FOR_CONTRACT: Dict[str, str] = {
    CONTRACT_TABLE_PREVIEW: ACTION_WRITE_TABLE_PREVIEW,
    CONTRACT_SCHEMA_PROFILE: ACTION_WRITE_SCHEMA_PROFILE,
    CONTRACT_CLEANED_OUTPUT: ACTION_WRITE_CLEANED_OUTPUT,
    CONTRACT_VALIDATION_VERDICT: ACTION_WRITE_VALIDATION_VERDICT,
}


def write_key_for(output_contract: str) -> str:
    """The single canonical key an agent with this ``output_contract`` may
    write. Every canonical key equals its contract's prefix, so this is also
    the key the runner hands an agent as its scoped write grant. Returns ``""``
    for an empty contract (a terminal agent that writes nothing)."""
    if not output_contract:
        return ""
    return _CONTRACT_PREFIX.get(output_contract, "")


class ContractError(ValueError):
    """Raised when an envelope violates the contract rules."""


@dataclass
class HandoffEnvelope:
    """The message between agents. Carries references, never content.

    Attributes:
        run_id:        the run this envelope belongs to.
        from_agent:    who produced this envelope (the previous agent).
        to_agent:      who is expected to consume it next.
        handoff_type:  semantic label, e.g. ``schema_request``.
        input_keys:    keys the receiving agent is allowed/expected to read.
        output_contract: the kind of artifact the receiving agent will produce.
        context_summary: a short human-readable note (the only "content" that
            travels, and it is a summary, not the payload).
        allowed_actions: subset of :data:`ALLOWED_ACTIONS` the receiving agent
            may perform.
    """

    run_id: str
    from_agent: str
    to_agent: str
    handoff_type: str
    input_keys: List[str] = field(default_factory=list)
    output_contract: str = ""
    context_summary: str = ""
    allowed_actions: List[str] = field(default_factory=list)

    # -- validation ------------------------------------------------------
    def validate_inbound(self, store: ArtifactStore) -> None:
        """Check the inbound envelope before the receiving agent runs:

        - every ``input_key`` exists in the store (an agent must not run
          against absent inputs);
        - every ``allowed_action`` is a known action (closed vocabulary);
        - if ``input_keys`` is non-empty, ``read_artifact`` is granted;
        - if ``output_contract`` carries a required write action, that action
          is granted — so ``allowed_actions`` matches the declared contract
          instead of being decorative.

        Raises :class:`ContractError` on any violation."""
        missing = [k for k in self.input_keys if not store.has(k)]
        if missing:
            raise ContractError(
                f"{self.to_agent}: input keys missing from store: {missing}"
            )
        unknown = [a for a in self.allowed_actions if a not in ALLOWED_ACTIONS]
        if unknown:
            raise ContractError(
                f"{self.to_agent}: unknown allowed_actions: {unknown}"
            )
        # An envelope that declares ``input_keys`` is promising to read from
        # the store, so it must be granted ``read_artifact`` — otherwise the
        # keys are decorative (the scoped view would deny every read anyway,
        # but the grant should say so up front).
        if self.input_keys and ACTION_READ_ARTIFACT not in self.allowed_actions:
            raise ContractError(
                f"{self.to_agent}: input_keys declared but read_artifact not "
                f"in allowed_actions {self.allowed_actions}"
            )
        # An envelope that declares an ``output_contract`` must be granted the
        # write action that backs that contract. Without this, ``allowed_actions``
        # is just a label — the real power flows from the contract key. Tying
        # the grant to the contract makes the envelope an honest capability
        # token: the permission and the obligation match.
        required = _REQUIRED_ACTION_FOR_CONTRACT.get(self.output_contract)
        if required is not None and required not in self.allowed_actions:
            raise ContractError(
                f"{self.to_agent}: output_contract {self.output_contract!r} "
                f"requires action {required!r} in allowed_actions "
                f"{self.allowed_actions}"
            )

    def validate_outbound(self, output_keys: List[str]) -> None:
        """Check that the keys an agent actually wrote match its declared
        ``output_contract``. Raises :class:`ContractError` on mismatch."""
        if not self.output_contract:
            if output_keys:
                raise ContractError(
                    f"{self.from_agent}: wrote {output_keys} but declared "
                    "no output_contract"
                )
            return
        if self.output_contract not in OUTPUT_CONTRACTS:
            raise ContractError(
                f"{self.from_agent}: unknown output_contract "
                f"{self.output_contract!r}"
            )
        prefix = _CONTRACT_PREFIX[self.output_contract]
        bad = [k for k in output_keys if not k.startswith(prefix + ".")
               and k != prefix]
        if bad:
            raise ContractError(
                f"{self.from_agent}: wrote {bad} which does not match "
                f"output_contract {self.output_contract!r} (prefix {prefix!r})"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "handoff_type": self.handoff_type,
            "input_keys": list(self.input_keys),
            "output_contract": self.output_contract,
            "context_summary": self.context_summary,
            "allowed_actions": list(self.allowed_actions),
        }
