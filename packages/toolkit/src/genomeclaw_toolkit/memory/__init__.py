"""Memory-note schema + validator for the agent's research-and-synthesis pattern.

This package codifies the `INV-A001` (Agent Memory Provenance) contract as
machine-readable validation. The canonical writer is the agent inside the
sandbox; the Python validator here is:

- A reference spec for what a well-formed memory note looks like.
- Test scaffolding that lets `tests/invariants/test_invA001_*.py` exercise
  the rejection rules without needing a live agent.
- A possible future CI gate that audits memory notes pulled out of the
  sandbox for compliance.

The agent's system prompt at
[packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](
../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) teaches
the agent to comply with this schema. The two surfaces — the prompt + the
validator — must stay in sync; that's enforced by
[test_agent_system_prompt_contract.py](
../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py).
"""

from genomeclaw_toolkit.memory.note_validator import (
    MemoryNote,
    MemoryNoteValidationError,
    validate_memory_note,
)

__all__ = [
    "MemoryNote",
    "MemoryNoteValidationError",
    "validate_memory_note",
]
