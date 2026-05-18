"""LOFTEE plugin's ``LoF.pm`` + ``gerp_dist.pl`` compile cleanly inside the toolkit image.

The 2026-05-14 real-data smoke surfaced a silent regression: ``LoF.pm``
requires ``Bio::Perl``, which wasn't installed alongside ``ensembl-vep``
in the image's micromamba env. VEP raises this as a WARNING (not a
fatal error), so the run keeps going and ``loftee_lof`` columns silently
end up NULL on every variant. Easy to miss until you query post-run.

The 2026-05-15 follow-up smoke surfaced a *second* silent regression in
the same shape: LoF.pm transitively loads ``gerp_dist.pl`` (LOFTEE's
GERP-bigwig reader) at runtime via ``do``. ``perl -c LoF.pm`` doesn't
recurse into ``do``-loaded scripts, so it passes even when
``gerp_dist.pl``'s own deps (``Bio::DB::BigFile`` from
``perl-bio-bigfile``) are missing. Result: ``loftee_lof`` columns stay
NULL even with ``LoF.pm`` parsing cleanly. Both helper scripts get their
own ``perl -c`` test below.

These tests pin the contract: the LoF.pm plugin file + every helper
``do``-loaded by it must ``perl -c``-parse cleanly — that's the cheapest
possible check that all modules they ``use`` (``Bio::Perl``, ``DBI``,
``DBD::SQLite``, ``Bio::DB::BigFile``, the various ``Bio::EnsEMBL::*``
modules) are reachable from VEP's perl ``@INC``.

The tests are ``needs_bio`` because they require the toolkit image's
perl + plugin layout. On a bare host venv they skip.
"""

from __future__ import annotations

import subprocess

import pytest

_LOFTEE_PLUGIN_DIR = "/opt/vep/.vep/Plugins"
_LOF_PLUGIN_PATH = f"{_LOFTEE_PLUGIN_DIR}/LoF.pm"
_GERP_HELPER_PATH = f"{_LOFTEE_PLUGIN_DIR}/gerp_dist.pl"
_VEP_PERL = "/opt/conda-vep/bin/perl"


def _perl_c(path: str) -> subprocess.CompletedProcess[str]:
    """Run ``perl -c <path>`` with the VEP-bundled perl + capture output."""
    return subprocess.run(
        [_VEP_PERL, "-c", path],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.needs_bio
def test_lof_plugin_compiles_with_vep_perl_inside_image() -> None:
    """``perl -c LoF.pm`` exits 0 — all the modules ``LoF.pm`` ``use``s resolve.

    Specifically defends against the 2026-05-14 regression where
    ``Bio::Perl`` was missing from the VEP env. ``Bio::Perl`` is one
    of LoF.pm's first imports (line 46); without it the plugin silently
    fails to compile and ``loftee_lof`` columns stay NULL.

    Runs the VEP-bundled perl directly so we don't depend on PATH order
    or ``vep --help`` behavior; just probes the canonical install layout.
    """
    proc = _perl_c(_LOF_PLUGIN_PATH)
    # ``perl -c`` writes either "<file> syntax OK" on success or a
    # compile error on failure. Exit 0 on success.
    assert proc.returncode == 0, (
        f"LoF.pm failed to compile (rc={proc.returncode}):\n"
        f"stderr:\n{proc.stderr}\n"
        f"stdout:\n{proc.stdout}\n"
        "Most likely cause: ``perl-bioperl`` (or another Bio::* dependency) "
        "missing from the VEP env. Add to Dockerfile stage 1a's bioconda install."
    )


@pytest.mark.needs_bio
def test_gerp_dist_helper_compiles_with_vep_perl_inside_image() -> None:
    """``perl -c gerp_dist.pl`` exits 0 — Bio::DB::BigFile + friends resolve.

    LoF.pm runs ``do "$plugin_dir/gerp_dist.pl"`` at LOFTEE init time to
    load the bigwig reader for GERP conservation scores. ``perl -c
    LoF.pm`` doesn't recurse into ``do``-loaded files, so this regression
    can hide behind a passing LoF.pm check (verified the hard way during
    the 2026-05-15 real-data smoke: LoF.pm parsed clean, but every
    variant's ``loftee_lof`` column was still NULL because gerp_dist.pl
    failed to compile on missing ``Bio::DB::BigFile``).

    Probing it explicitly with ``perl -c`` here is a millisecond-scale
    test that catches the bug before another 4-hour real-data run does.
    """
    proc = _perl_c(_GERP_HELPER_PATH)
    assert proc.returncode == 0, (
        f"gerp_dist.pl failed to compile (rc={proc.returncode}):\n"
        f"stderr:\n{proc.stderr}\n"
        f"stdout:\n{proc.stdout}\n"
        "Most likely cause: ``perl-bio-bigfile`` (or another Bio::DB::BigFile "
        "dependency) missing from the VEP env. Add to Dockerfile stage 1a's "
        "bioconda install."
    )
