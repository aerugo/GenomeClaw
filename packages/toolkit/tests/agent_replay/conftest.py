"""Conftest for agent-replay LLM-judge tests (Phase 5 of agent-synthesis-over-rich-tool-data).

The LLM-judge harness calls a real model (`gpt-5.5` per project pin) to
evaluate agent replies for *faithful* + *understandable* synthesis of
tool-result data. Per `INV-P001` Privacy Default the harness is
**default-skip**: only runs when `GENOMECLAW_REPLAY_LLM=gpt-5.5` and
`OPENAI_API_KEY` are both set.

Pinned model is `gpt-5.5`. Cheaper substitutes (gpt-4o-mini, gpt-5-mini)
are NOT used in this project — the judge needs the reasoning ceiling to
distinguish faithful synthesis from robotic transcription.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session")
def replay_llm_model() -> str:
    """Model id for the LLM-judge. Skip cleanly when env var is unset."""
    model = os.environ.get("GENOMECLAW_REPLAY_LLM")
    if not model:
        pytest.skip(
            "GENOMECLAW_REPLAY_LLM not set — agent-replay LLM-judge tests skipped "
            "(default-skip preserves INV-P001 no-egress). "
            "To enable: export GENOMECLAW_REPLAY_LLM=gpt-5.5"
        )
    return model


@pytest.fixture(scope="session")
def openai_api_key() -> str:
    """OpenAI API key for the LLM-judge."""
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        pytest.skip(
            "OPENAI_API_KEY not set; cannot reach gpt-5.5 for judge calls"
        )
    return key
