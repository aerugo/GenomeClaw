"""Install the GenomeClaw agent system prompt into the sandbox openclaw.json.

Runs inside the Dockerfile after `openclaw plugins install` + the web_search
config-set step. Reads the prompt text off disk (the COPY step lands it at
/sandbox/build/genomeclaw/sandbox/agent-system-prompt.md) and uses
`openclaw config set --batch-file` to write
`agents.list[].systemPromptOverride` with the multi-line text intact — shell
heredocs would mangle escape sequences.

Verified by:
- tests/invariants/test_agent_system_prompt_contract.py (content gates on the prompt file in the repo)
- tests/invariants/test_invP001_sandbox_web_egress_contract.py (native OpenAI search enabled-by-default; no managed provider pinned; web_fetch off — per INV-P001 v1.7)
- A future Phase 2 needs_sandbox gate that reads the baked openclaw.json + asserts agents.list[0].systemPromptOverride is non-empty.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

PROMPT_PATH = pathlib.Path("/sandbox/build/genomeclaw/sandbox/agent-system-prompt.md")
BATCH_PATH = pathlib.Path("/tmp/agents-batch.json")  # noqa: S108 — Docker build, ephemeral

prompt = PROMPT_PATH.read_text()
batch = [
    {
        "path": "agents.list",
        "value": [
            {
                "id": "genomeclaw",
                "name": "GenomeClaw Assistant",
                "default": True,
                "systemPromptOverride": prompt,
            }
        ],
    }
]
BATCH_PATH.write_text(json.dumps(batch))

result = subprocess.run(
    ["openclaw", "config", "set", "--batch-file", str(BATCH_PATH)],
    check=False,
)
sys.exit(result.returncode)
