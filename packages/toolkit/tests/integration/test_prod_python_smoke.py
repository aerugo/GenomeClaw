"""Phase 6 — production-Python smoke gate.

Phase 3 was declared complete with 677 tests green on the host venv
(Python 3.13.1). The toolkit image runs Python 3.11.15. The
``SiblingMountablePath(Path)`` form works on 3.12+ natively but fails on
3.11 with ``AttributeError: type object 'SiblingMountablePath' has no
attribute '_flavour'``. The Phase 5 smoke surfaced the skew in 30
seconds.

Phase 6 adds a ``needs_prod_python`` marker. Tests so marked run a probe
inside the toolkit image via ``docker run`` and assert rc=0. This is the
regression that would have caught the Phase 3 misstep at completion.

Gated by ``GENOMECLAW_TOOLKIT_PRS_IMAGE`` + ``docker`` on PATH (the
existing convention used by ``needs_prs_runtime`` tests).

Phase plan: [phases/phase-6.md](../../../../docs/plans/active/path-crossing-discipline/phases/phase-6.md)
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.needs_prod_python


def _image() -> str:
    img = os.environ.get("GENOMECLAW_TOOLKIT_PRS_IMAGE")
    if not img:
        pytest.skip("GENOMECLAW_TOOLKIT_PRS_IMAGE not set")
    return img


# ---------------------------------------------------------------------------
# Test 5 — SiblingMountablePath constructs inside the image's Python
# ---------------------------------------------------------------------------


def test_prod_python_path_subclass_constructs_inside_image() -> None:
    """``SiblingMountablePath('/tmp/x')`` returns a valid instance inside the
    prod-Python.

    Would have caught the Phase 3 Path-subclass ``_flavour`` AttributeError
    at phase-completion time instead of at smoke-time."""
    if shutil.which("docker") is None:
        pytest.skip("docker not on PATH")
    image = _image()

    probe = (
        "from pathlib import Path; "
        "from genomeclaw_toolkit.prep._paths import SiblingMountablePath; "
        "p = SiblingMountablePath('/tmp/x'); "
        "assert isinstance(p, Path); "
        "assert p.name == 'x'; "
        "print('OK')"
    )
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            image,
            "/opt/genomeclaw/toolkit/.venv/bin/python",
            "-c",
            probe,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"prod-Python probe failed (rc={result.returncode}): "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "OK" in result.stdout, f"probe didn't print OK; stdout={result.stdout!r}"


# ---------------------------------------------------------------------------
# Test 6 — factory rejection of canonical-mount works in prod-Python
# ---------------------------------------------------------------------------


def test_prod_python_factory_rejects_canonical_mount_inside_image() -> None:
    """The Phase 6 factory tightening (reject ``/mnt/genomeclaw/...``) holds
    inside the toolkit image's Python 3.11.

    Catches the case where a Python version difference quietly disables the
    rejection (e.g., a pathlib API that behaves differently)."""
    if shutil.which("docker") is None:
        pytest.skip("docker not on PATH")
    image = _image()

    # Probe is multi-line to avoid the `try:`-after-semicolons SyntaxError;
    # ``python -c`` accepts \n-separated lines fine.
    probe = (
        "import os\n"
        "from pathlib import Path\n"
        "os.environ['GENOMECLAW_SCRATCH_DIR'] = '/Volumes/x/_scratch'\n"
        "os.environ['GENOMECLAW_HOST_ROOTS'] = '/Volumes/x/_scratch'\n"
        "from genomeclaw_toolkit.prep._paths import DooDPathError, as_sibling_mountable\n"
        "try:\n"
        "    as_sibling_mountable(Path('/mnt/genomeclaw/scratch/foo'))\n"
        "    raise SystemExit('FAIL: factory accepted canonical-mount path')\n"
        "except DooDPathError as e:\n"
        "    assert '/mnt/genomeclaw' in str(e), str(e)\n"
        "    assert '/Volumes/x/_scratch/foo' in str(e), str(e)\n"
        "    print('OK')\n"
    )
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            image,
            "/opt/genomeclaw/toolkit/.venv/bin/python",
            "-c",
            probe,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"prod-Python factory rejection probe failed (rc={result.returncode}): "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "OK" in result.stdout, f"probe didn't print OK; stdout={result.stdout!r}"
