"""agent_network_demo — agents pass keys (references), not blobs.

A small, deterministic demo of a multi-agent pipeline where the handoff
envelope between agents carries *references* to artifacts in a shared
artifact store, not the artifact content itself. An append-only event log
records who did what, with which input/output keys.
"""

__all__ = [
    "artifact_store",
    "event_log",
    "contracts",
    "agents",
    "demo_runner",
]