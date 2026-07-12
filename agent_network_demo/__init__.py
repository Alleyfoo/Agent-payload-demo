"""agent_network_demo — agents pass keys (references), not blobs.

A small, deterministic demo of a multi-agent pipeline where the handoff
envelope between agents carries *references* to artifacts in a shared
artifact store, not the artifact content itself. An event log, append-only
through the application API, records input/output keys and runner receipts.
"""

__all__ = [
    "artifact_store",
    "event_log",
    "contracts",
    "agents",
    "demo_runner",
]
