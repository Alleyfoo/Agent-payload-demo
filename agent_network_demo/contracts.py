"""Contracts: the handoff envelope between agents + the action vocabulary.

The envelope is the *only* thing that passes from one agent to the next,
and it carries **references** (keys into the artifact store), never content.
An agent declares, up front, what it will read (``input_keys``) and what kind
of artifact it promises to produce (``output_contract``). The runner
enforces both before and after the agent runs — so a misbehaving agent cannot
silently read or write the wrong thing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from agent_network_demo.artifact_store import ArtifactStore

# ---------------------------------------------------------------------------
# Action vocabulary — the closed set of things any agent may do.
# Keeping this finite and explicit is the "keys not blobs" security story:
# an agent's powers are declared on the envelope, not invented at runtime.
# ---------------------------------------------------------------------------

ACTION_READ_ARTIFACT = "read_artifact"
ACTION_WRITE_SCHEMA_PROFILE = "write_schema_profile"
ACTION_WRITE_CLEANED_OUTPUT = "write_cleaned_output"
ACTION_WRITE_VALIDATION_VERDICT = "write_validation_verdict"

ALLOWED_ACTIONS: Set[str] = {
    ACTION_READ_ARTIFACT,
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
        """Check that every ``input_key`` exists in the store before the
        receiving agent runs. Raises :class:`ContractError` if any are
        missing — an agent must not run against absent inputs."""
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