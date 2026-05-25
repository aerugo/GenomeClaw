# Phase 3: `host doctor` — Detect Colima Mounts That Don't Cover the Derived Dir

**Status**: Pending
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Teach `bin/genomeclaw host doctor` to detect the operator-side failure mode where colima's `mounts:` list does not cover `$GENOMECLAW_DERIVED_DIR`. In that state, the docker-wrapped `bin/genomeclaw host service` silently can't see the derived directory and returns `no_active_run` — the operator's onboarded agent then says "no derived data" without it being obvious why. The new check emits a warning-level finding naming both fixes (`bin/genomeclaw host setup` OR `GENOMECLAW_NATIVE=1`) so the operator isn't reading agent replies trying to figure out their colima config.

## Scope Boundaries

- **In scope**: a new `_check_colima_mounts_cover_derived` function in `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/host.py`; wiring it into the existing `host doctor` finding pipeline; a parametrized integration test.
- **Out of scope**: making `bin/genomeclaw host service` itself auto-fall-back to native uvicorn when colima mounts don't cover the dir (heavier lift; doctor warning is the operator-facing stopgap). The Dockerfile bakes (Phase 1) and onboarding script rewrite (Phase 2) are prerequisite — they should already be merged before Phase 3 starts so the operator-experience-tracking story is coherent.

## Invariants Enforced in This Phase

- **INV-D006** DooD-Safe Path Annotation — the docker-wrapped host service relies on the path-resolution layer working correctly across the colima boundary. The colima mounts being present and covering the derived dir is the operator-side prerequisite. The doctor check is the detection point; the existing INV-D006 enforcement (typed wrappers, shim regex) is the code-side enforcement.

---

## TDD Steps

### Step 3.1 — RED: Write Failing Tests

**Test cases** (all in `packages/toolkit/tests/integration/test_host_doctor_colima_mounts_coverage.py`):

1. `test_doctor_colima_mounts_empty_warns_when_derived_is_external_drive` — fixture: write a `colima.yaml` with `mounts: []`; set `GENOMECLAW_DERIVED_DIR=/Volumes/MyUSB/genomeclaw/derived` (an external-drive path). Run `host doctor --json`; assert `findings[]` contains an entry with `severity == "warning"`, `name == "colima_mounts_cover_derived"`, and `message` contains both "host setup" and "GENOMECLAW_NATIVE=1".
2. `test_doctor_colima_mounts_covers_derived_no_warning` — fixture: write a `colima.yaml` with `mounts: [{location: /Volumes, writable: true}]`; same `GENOMECLAW_DERIVED_DIR`. Assert the warning is absent (no `colima_mounts_cover_derived` finding emitted).
3. `test_doctor_colima_mounts_populated_but_doesnt_cover_warns` — fixture: write a `colima.yaml` with `mounts: [{location: /Users/hugi, writable: true}]`; same external-drive `GENOMECLAW_DERIVED_DIR`. Assert the warning IS emitted (some mounts present but none cover the derived dir).
4. `test_doctor_colima_mounts_no_yaml_no_warning` — fixture: `~/.colima/default/colima.yaml` does not exist. Assert no `colima_mounts_cover_derived` finding (different failure mode; covered by the existing stale-mount check, not this one).
5. `test_doctor_colima_mounts_derived_on_system_disk_no_warning` — fixture: `mounts: []` AND `GENOMECLAW_DERIVED_DIR=/Users/hugi/genomeclaw/derived` (a system-disk path). Assert the warning is absent — system-disk paths are always visible to the engine VM via the default `$HOME` mount, so the check shouldn't fire.
6. `test_doctor_exit_zero_when_only_finding_is_this_warning` — assert the doctor's exit code is 0 (warnings are non-blocking, matching the existing stale-mount precedent).

**Test sketch**:

```python
"""INV-D006: colima mounts must cover the operator's derived dir for the
docker-wrapped `bin/genomeclaw host service` to see it. Doctor warns
when the mounts list and derived dir disagree on an external drive.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
GENOMECLAW = REPO_ROOT / "bin" / "genomeclaw"


@pytest.fixture
def fake_colima_yaml(tmp_path, monkeypatch):
    """Materialise a colima.yaml fixture + point the doctor at it."""
    yaml_path = tmp_path / "colima.yaml"
    monkeypatch.setenv("GENOMECLAW_COLIMA_YAML", str(yaml_path))
    return yaml_path


def _run_doctor(env_overrides: dict[str, str]) -> tuple[int, dict]:
    proc = subprocess.run(
        [str(GENOMECLAW), "host", "doctor", "--json"],
        capture_output=True, text=True, env={**os.environ, **env_overrides},
        check=False,
    )
    return proc.returncode, json.loads(proc.stdout)


@pytest.mark.parametrize(
    ("mounts_yaml_body", "derived_dir", "expect_warning"),
    [
        # 1. mounts: [] + derived on external drive → warn
        ("mounts: []\n", "/Volumes/MyUSB/genomeclaw/derived", True),
        # 2. mounts cover derived → no warn
        ("mounts:\n  - location: /Volumes\n    writable: true\n",
         "/Volumes/MyUSB/genomeclaw/derived", False),
        # 3. mounts present but don't cover → warn
        ("mounts:\n  - location: /Users/hugi\n    writable: true\n",
         "/Volumes/MyUSB/genomeclaw/derived", True),
        # 5. mounts: [] but derived on system disk → no warn
        ("mounts: []\n", "/Users/hugi/genomeclaw/derived", False),
    ],
    ids=["empty-mounts-external", "covers-external", "populated-doesnt-cover", "empty-mounts-system"],
)
def test_invD006_doctor_colima_mounts_cover_derived(
    fake_colima_yaml: Path,
    mounts_yaml_body: str,
    derived_dir: str,
    expect_warning: bool,
) -> None:
    fake_colima_yaml.write_text(mounts_yaml_body)
    rc, doctor_json = _run_doctor({
        "GENOMECLAW_DERIVED_DIR": derived_dir,
        "GENOMECLAW_COLIMA_YAML": str(fake_colima_yaml),
    })
    findings = {f["name"]: f for f in doctor_json.get("findings", [])}
    has_warning = "colima_mounts_cover_derived" in findings
    assert has_warning == expect_warning, (
        f"expected warning={expect_warning}, got {has_warning}; "
        f"findings={list(findings.keys())}"
    )
    if expect_warning:
        msg = findings["colima_mounts_cover_derived"]["message"]
        assert "host setup" in msg
        assert "GENOMECLAW_NATIVE=1" in msg
        assert findings["colima_mounts_cover_derived"]["severity"] == "warning"
```

After writing the tests, run them and **confirm they fail for the intended reason** (`colima_mounts_cover_derived` not a recognized finding name). Paste the failing output into `work-notes.md`.

### Step 3.2 — GREEN: Minimal Implementation

Add to `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/host.py`:

```python
import os
import re
from pathlib import Path

# Reasonable upper bound for re-reading the colima yaml — it's tens of lines
# for most setups, hundreds at most. A bigger file is suspicious and we'd
# rather surface that than blow up the doctor's runtime.
_COLIMA_YAML_MAX_BYTES = 1024 * 1024  # 1 MiB

# Mount entries in colima.yaml look like:
#   mounts:
#     - location: /Volumes/MyUSB
#       writable: true
# Use a forgiving regex rather than pulling in a yaml dep just for this.
# False positives (line in a comment that happens to start with `- location:`)
# are an acceptable trade — the worst case is a missed warning, not a
# wrong-warning, because we test coverage by path-prefix.
_LOCATION_LINE_RE = re.compile(r"^\s*-\s*location\s*:\s*[\"']?([^\"'\s]+)")


def _read_colima_mounts(colima_yaml_path: Path) -> list[Path] | None:
    """Return the list of mounted host paths, or None if the file is absent.

    Returns [] if the file exists but has `mounts: []` or no mounts list.
    """
    if not colima_yaml_path.exists():
        return None
    if colima_yaml_path.stat().st_size > _COLIMA_YAML_MAX_BYTES:
        # Suspicious; treat as "can't determine" rather than parsing forever.
        return None
    text = colima_yaml_path.read_text()
    # Strip the COMMENTED-OUT example block — anything after `# Default: []` on
    # the `mounts:` key in stock colima.yaml. We only care about real entries.
    mounts: list[Path] = []
    for line in text.splitlines():
        # Skip lines starting with `#` (full-line comments).
        if line.lstrip().startswith("#"):
            continue
        m = _LOCATION_LINE_RE.match(line)
        if m:
            mounts.append(Path(m.group(1)).expanduser())
    return mounts


def _path_is_under_any(target: Path, candidates: list[Path]) -> bool:
    """True iff `target` is the same as, or a descendant of, any `candidates`."""
    try:
        target_resolved = target.resolve()
    except OSError:
        return False
    for c in candidates:
        try:
            target_resolved.relative_to(c.resolve())
            return True
        except (ValueError, OSError):
            continue
    return False


def _check_colima_mounts_cover_derived(
    colima_yaml_path: Path,
    derived_dir: Path,
) -> dict | None:
    """Return a doctor-finding dict if colima's mounts don't cover derived_dir,
    else None.

    Skipped when:
    - colima.yaml doesn't exist (the existing stale-mount check covers that)
    - derived_dir is under $HOME (colima's default $HOME-shared behavior covers it)
    """
    mounts = _read_colima_mounts(colima_yaml_path)
    if mounts is None:
        return None  # no colima.yaml — different check's territory

    home = Path.home().resolve()
    try:
        derived_resolved = derived_dir.resolve()
    except OSError:
        return None
    try:
        derived_resolved.relative_to(home)
        return None  # under $HOME, colima default mount covers it
    except ValueError:
        pass

    if _path_is_under_any(derived_resolved, mounts):
        return None  # explicitly covered

    return {
        "name": "colima_mounts_cover_derived",
        "severity": "warning",
        "message": (
            f"colima's mounts: list does not cover GENOMECLAW_DERIVED_DIR={derived_dir}. "
            f"The docker-wrapped `bin/genomeclaw host service` will not see your derived "
            f"directory and the agent will report no_active_run. "
            f"Two fixes: re-run `bin/genomeclaw host setup` to add the mount, "
            f"OR run the host service natively via `GENOMECLAW_NATIVE=1 bin/genomeclaw host service`."
        ),
        "details": {
            "derived_dir": str(derived_dir),
            "colima_yaml": str(colima_yaml_path),
            "mounts_found": [str(m) for m in mounts],
        },
    }
```

Wire it into the existing `host doctor` command:

```python
# In the body of the doctor function, alongside the existing checks:
colima_yaml = Path(
    os.environ.get("GENOMECLAW_COLIMA_YAML", Path.home() / ".colima" / "default" / "colima.yaml")
)
derived_dir = Path(os.environ.get("GENOMECLAW_DERIVED_DIR", "/mnt/genomeclaw/derived"))
finding = _check_colima_mounts_cover_derived(colima_yaml, derived_dir)
if finding is not None:
    findings.append(finding)
```

The doctor's exit code calculation already treats warnings as non-blocking (per the existing stale-mount precedent); the new finding rides on the same path.

**Files affected**:
- `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/host.py`: ~80 lines added.

### Step 3.3 — REFACTOR

With tests green:

- Extract `_path_is_under_any` to a module-level helper if it's used in more than one check (rule of three; right now it's one use, leave inline).
- Tighten the regex if colima's yaml format reveals edge cases (quoted paths, paths with spaces). The current regex handles unquoted + single-quoted + double-quoted; the test parametrization should cover at least the unquoted case.
- Confirm the warning message reads cleanly when surfaced through `--json` (no inline ANSI codes, no extra newlines).
- Update `bin/genomeclaw host doctor`'s help text to mention the new check.

---

## Implementation Details

### Why regex instead of pyyaml

The toolkit doesn't currently depend on `pyyaml` (it has `ruamel.yaml` via a transitive dep through some bioinformatics tool, but pulling that into the doctor would be a new direct dep). For the narrow `mounts:` block shape, a 2-line regex is sufficient and zero-cost. If colima ever changes its YAML format, we revisit.

### Edge Cases to Handle

- **Paths with `~`**: `Path("~/foo").expanduser()` is applied to mount entries (some operators hand-edit colima.yaml with `~/projects` style). Tested via fixture.
- **Symlinked external drive**: `derived_dir.resolve()` and `mount.resolve()` both follow symlinks; if the operator has `/Volumes/Genome_Work` → `/private/...`, the comparison still works.
- **`$HOME` derived paths**: deliberately skipped (no warning) because colima's default behavior shares `$HOME` even with `mounts: []`. The existing macOS Sequoia + Full Disk Access caveat applies, but it's a separate failure mode handled by the existing readonly-mount check.
- **`GENOMECLAW_DERIVED_DIR` unset**: defaults to `/mnt/genomeclaw/derived` (the in-container canonical path). That path doesn't exist on the host, so `resolve()` returns the literal path (since it's absolute), `relative_to(home)` fails (not under home), `_path_is_under_any` checks if it's under any mount — typically not, so the warning fires. Edge case: if the operator hasn't set the env var AND hasn't run `host setup`, the warning fires correctly because they need to either fix mounts or use native.

### Error Handling

- File read errors → return `None` (treat as "can't determine"). Better to under-warn than crash the doctor.
- Malformed yaml (which our regex doesn't truly parse) → may miss entries. The test parametrization includes the most common shapes; truly bizarre files surface as "the warning fires when it shouldn't" which the operator can then debug.

### Privacy / Egress Notes

- The doctor's JSON output may include `GENOMECLAW_DERIVED_DIR` (which is a host filesystem path, not a secret). No secret material flows.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/host.py` | MODIFY | Add `_check_colima_mounts_cover_derived` + helpers; wire into doctor. |
| `packages/toolkit/tests/integration/test_host_doctor_colima_mounts_coverage.py` | CREATE | 4 parametrized cases + 1 exit-code test + 1 no-yaml case. |
| `README.md` | MODIFY (small) | (1) Under "Day-to-day commands" (line 84 area), extend the `host doctor` description to mention the new colima-mounts-coverage check. (2) Add a Troubleshooting entry: **"colima mounts: [] — agent reports `no_active_run` from a healthy-looking sandbox"** pointing at the new doctor warning and the two fixes (`host setup` OR `GENOMECLAW_NATIVE=1`). |

---

## Verification

```bash
# Run Phase 3 tests
cd packages/toolkit
.venv/bin/pytest tests/integration/test_host_doctor_colima_mounts_coverage.py -v

# Manual sanity check: simulate empty-mounts scenario
mkdir -p /tmp/fake-colima
cat > /tmp/fake-colima/colima.yaml <<EOF
mounts: []
EOF
GENOMECLAW_COLIMA_YAML=/tmp/fake-colima/colima.yaml \
GENOMECLAW_DERIVED_DIR=/Volumes/MyUSB/genomeclaw/derived \
  bin/genomeclaw host doctor --json | jq '.findings[] | select(.name == "colima_mounts_cover_derived")'
# Expect: a JSON object with severity=warning and a message naming both fixes.

# Confirm no regression on a covered scenario
cat > /tmp/fake-colima/colima.yaml <<EOF
mounts:
  - location: /Volumes
    writable: true
EOF
GENOMECLAW_COLIMA_YAML=/tmp/fake-colima/colima.yaml \
GENOMECLAW_DERIVED_DIR=/Volumes/MyUSB/genomeclaw/derived \
  bin/genomeclaw host doctor --json | jq '.findings[] | select(.name == "colima_mounts_cover_derived")'
# Expect: empty (no such finding).

# Full doctor sanity
bin/genomeclaw host doctor
echo "exit: $?"
# Expect: previous-behavior preserved; new warning fires only when applicable; exit 0 if only finding is the new warning.
```

---

## Completion Criteria

- [ ] All 6 test cases pass (4 parametrized + no-yaml + exit-code).
- [ ] Static checks pass (mypy strict, ruff clean).
- [ ] At least one test references `INV-D006` in its name or docstring.
- [ ] `bin/genomeclaw host doctor` exit code is 0 when the only finding is the new warning (matches stale-mount precedent).
- [ ] Manual sanity check returns the expected JSON shape.
- [ ] No raw genomic data, secrets, or sample IDs added to fixtures.
- [ ] `work-notes.md` updated with RED output, decisions, and final state.
- [ ] Phase status updated to "Complete" in `development-plan.md`.
