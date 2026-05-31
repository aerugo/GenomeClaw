"""`INV-P002` — the plugin's OpenShell policy preset enforces the documented network floor.

The policy preset at
[packages/nemoclaw-plugin/policy-preset.yaml](../../../../nemoclaw-plugin/policy-preset.yaml)
is one of three runtime enforcement layers for `INV-P002` (per
[INVARIANTS.md § INV-P002](../../../../../docs/reference/INVARIANTS.md)):

1. Host service shaping — verified by the per-route Pydantic models
   (Slices A + B + C of Phase 5).
2. Plugin output shaping — verified by the vitest envelope tests
   under [packages/nemoclaw-plugin/tests/](../../../../nemoclaw-plugin/tests/).
3. **OpenShell L7 proxy + SSRF guard** — verified here. The policy
   preset must (a) allowlist exactly the documented v0 read endpoints,
   (b) allow only GET methods, and (c) carry the RFC 1918
   `allowed_ips:` block that OpenShell's SSRF guard requires for
   `host.openshell.internal` resolution.

This test runs on the host venv (no `needs_bio`) — it only parses YAML.
The sandbox-side check (`INV-D002`: no bio binaries baked into the
sandbox image) lives in [test_invD002_sandbox_image_no_bio_binaries.py](
test_invD002_sandbox_image_no_bio_binaries.py).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[4]
_POLICY_PRESET_PATH = _REPO_ROOT / "packages" / "nemoclaw-plugin" / "policy-preset.yaml"

# RFC 1918 ranges that OpenShell's SSRF guard requires for
# host.openshell.internal resolution to succeed. Documented in the
# policy-preset.yaml comment block + INV-P002.
_REQUIRED_ALLOWED_IPS: frozenset[str] = frozenset({"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"})

# The exact v0 endpoint surface (Phase 5 host service + Phase 6
# endpoints + Phase 6 Slice E v2 agent-driven PRS endpoints per Q8 v1.6).
# A future endpoint addition MUST extend this set *and* the policy
# preset together; the test pins the contract.
_ALLOWED_V0_PATHS: frozenset[str] = frozenset(
    {
        "/v1/health",
        "/v1/findings",
        "/v1/findings/*",
        "/v1/variants",
        "/v1/variants/*",
        "/v1/evidence/*",
        "/v1/provenance/*",
        "/v1/gene/*",
        # Phase 6 Slice E v2 — agent-driven PRS layer (Q8 v1.6).
        # Keyed by PGS Catalog ID; compute is agent-triggered async.
        "/v1/pgs/computed",
        "/v1/pgs/computed/*",
        "/v1/pgs/compute",
        "/v1/pgs/compute/*",
        "/v1/capabilities",
        # host-profile-personal-context Phase 3 — read-only host-profile
        # endpoints. Both GET; the agent retrieves the self-reported
        # personal-context profile before genome-informable turns.
        "/v1/host/profile",
        "/v1/host/profile/completeness",
    }
)

# The single POST path the policy preset legitimately allows in v0:
# the agent-triggered PRS compute enqueue (per Q8 v1.6). All other
# paths must remain GET-only. A future addition to this set must
# carry an INV-P002 review since POSTs widen the host-service write
# surface.
_ALLOWED_POST_PATHS: frozenset[str] = frozenset({"/v1/pgs/compute"})


@pytest.fixture(scope="module")
def policy_preset() -> dict[str, Any]:
    """Load + parse the plugin's policy-preset.yaml."""
    return yaml.safe_load(_POLICY_PRESET_PATH.read_text())


def _genomeclaw_endpoint(policy_preset: dict[str, Any]) -> dict[str, Any]:
    """Locate the single ``genomeclaw`` endpoint block in the preset."""
    policies = policy_preset["network_policies"]
    genomeclaw = policies["genomeclaw"]
    endpoints = genomeclaw["endpoints"]
    assert len(endpoints) == 1, (
        f"INV-P002: expected exactly one network endpoint in policy preset, got {len(endpoints)}"
    )
    return endpoints[0]


def test_invP002_policy_preset_targets_host_openshell_internal(
    policy_preset: dict[str, Any],
) -> None:
    """The single endpoint targets `host.openshell.internal:8645` only.

    Any other host or port would let the plugin reach destinations the
    architecture doesn't sanction. ``INV-P001`` extends this: outside of
    the agent endpoint + host service, the plugin reaches nothing.

    Port is 8645 (GenomeClaw-canonical; DevRelClaw uses 8643) per the
    2026-05-24 coexistence change — the preset + this assertion track it
    together.
    """
    ep = _genomeclaw_endpoint(policy_preset)
    assert ep["host"] == "host.openshell.internal"
    assert ep["port"] == 8645
    assert ep["enforcement"] == "enforce"


def test_invP002_policy_preset_carries_rfc1918_allowed_ips(
    policy_preset: dict[str, Any],
) -> None:
    """The `allowed_ips:` block must cover the three RFC 1918 ranges.

    OpenShell's SSRF guard rejects requests to private host-gateway IPs
    *unless* the policy explicitly allowlists them. Without this block,
    the plugin fails at runtime with `ssrf_denied: blocked: internal
    address` (per the docstring in the preset itself + INV-P002).
    """
    ep = _genomeclaw_endpoint(policy_preset)
    allowed = set(ep.get("allowed_ips", []))
    missing = _REQUIRED_ALLOWED_IPS - allowed
    assert not missing, (
        f"INV-P002: policy preset is missing required RFC 1918 ranges in "
        f"allowed_ips: {sorted(missing)}; full set was {sorted(allowed)}"
    )


def test_invP002_policy_preset_restricts_post_to_documented_paths(
    policy_preset: dict[str, Any],
) -> None:
    """Every rule's method is either GET, or POST against an allow-listed path.

    The host service is read-only by default; the only POST endpoint in v0
    is `/v1/pgs/compute` (per Q8 v1.6 — agent-triggered async PRS compute
    enqueue). A future regression that "helpfully" adds a POST allow rule
    for some other path (e.g. a write-finding endpoint) surfaces here.
    """
    ep = _genomeclaw_endpoint(policy_preset)
    for rule in ep["rules"]:
        allow = rule.get("allow")
        assert allow is not None, f"INV-P002: rule {rule!r} doesn't have an `allow:` block"
        method = allow.get("method")
        path = allow.get("path")
        if method == "GET":
            continue
        assert method == "POST", (
            f"INV-P002: rule {rule!r} allows method {method!r}; only GET or POST is permitted"
        )
        assert path in _ALLOWED_POST_PATHS, (
            f"INV-P002: POST is allowed on path {path!r}, but the only documented "
            f"POST surface in v0 is {sorted(_ALLOWED_POST_PATHS)} (per Q8 v1.6). "
            "Any other POST widens the host-service write surface — requires an "
            "explicit INV-P002 review."
        )


def test_invP002_policy_preset_path_set_matches_documented_surface(
    policy_preset: dict[str, Any],
) -> None:
    """Every allowed path is in the documented v0 endpoint set.

    Asserts both directions: no path is allowed that isn't documented
    (no accidental widening), and the documented set is the source of
    truth (a future endpoint must extend the test's set *and* the
    preset together).
    """
    ep = _genomeclaw_endpoint(policy_preset)
    rule_paths = {rule["allow"]["path"] for rule in ep["rules"]}
    unexpected = rule_paths - _ALLOWED_V0_PATHS
    assert not unexpected, (
        f"INV-P002: policy preset allows paths not in the documented v0 surface: "
        f"{sorted(unexpected)}. Either add them to _ALLOWED_V0_PATHS in this "
        "test (with the corresponding host-service route) or remove them from "
        "policy-preset.yaml."
    )


def test_invP002_policy_preset_includes_v1_gene_route(
    policy_preset: dict[str, Any],
) -> None:
    """The `/v1/gene/*` route (Phase 5 Slice C) is in the allowlist.

    Defends against a regression that would ship the gene endpoint
    server-side without extending the policy preset — the runtime would
    return 403 / SSRF-denied from the sandbox and silently break the
    plugin's `genomeclaw_gene` tool.
    """
    ep = _genomeclaw_endpoint(policy_preset)
    rule_paths = {rule["allow"]["path"] for rule in ep["rules"]}
    assert "/v1/gene/*" in rule_paths, (
        "INV-P002: policy preset is missing /v1/gene/* allow rule "
        "(Phase 5 Slice C shipped the route but the preset must follow)."
    )


def test_invP002_policy_preset_binaries_restricted_to_runtime(
    policy_preset: dict[str, Any],
) -> None:
    """`binaries:` restricts which executables may originate the connection.

    Only `openclaw` and `node` are legitimate callers. Anything else
    (curl, python, custom agent-written scripts) is denied at the
    OpenShell egress layer regardless of policy-preset path rules.
    """
    genomeclaw = policy_preset["network_policies"]["genomeclaw"]
    binary_paths = {b["path"] for b in genomeclaw["binaries"]}
    # At minimum: the openclaw binary + node runtime must be allowed.
    assert any("openclaw" in p for p in binary_paths), (
        f"INV-P002: openclaw binary missing from binaries allowlist: {binary_paths}"
    )
    assert any("node" in p for p in binary_paths), (
        f"INV-P002: node runtime missing from binaries allowlist: {binary_paths}"
    )


def test_invP002_policy_preset_allows_host_profile_paths(
    policy_preset: dict[str, Any],
) -> None:
    """The two read-only host-profile GET paths are in the allowlist (Phase 3).

    Defends against shipping the host-profile endpoints server-side
    without extending the policy preset — the plugin tool would then fail
    at runtime with an OpenShell L7 deny.
    """
    ep = _genomeclaw_endpoint(policy_preset)
    rule_paths = {rule["allow"]["path"] for rule in ep["rules"]}
    for path in ("/v1/host/profile", "/v1/host/profile/completeness"):
        assert path in rule_paths, (
            f"INV-P002: policy preset is missing the {path!r} allow rule "
            "(host-profile-personal-context Phase 3 shipped the route)."
        )


def test_invP002_policy_preset_host_profile_paths_are_get_only(
    policy_preset: dict[str, Any],
) -> None:
    """The host-profile paths are GET-only — no write surface added (INV-P002)."""
    ep = _genomeclaw_endpoint(policy_preset)
    for rule in ep["rules"]:
        allow = rule["allow"]
        if allow["path"] in ("/v1/host/profile", "/v1/host/profile/completeness"):
            assert allow["method"] == "GET", (
                f"INV-P002: host-profile path {allow['path']!r} must be GET-only; "
                f"got {allow['method']!r}"
            )
