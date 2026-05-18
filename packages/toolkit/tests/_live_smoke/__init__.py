"""Live-smoke helpers — staging + sandbox orchestration for `live_llm` tests.

The modules here are imported only by tests marked `@pytest.mark.live_llm`;
they shell out to `docker run` and require `OPENAI_API_KEY` +
`GENOMECLAW_SANDBOX_IMAGE` to be set. The auto-skip in
[tests/conftest.py](../conftest.py) keeps them out of default CI.
"""
