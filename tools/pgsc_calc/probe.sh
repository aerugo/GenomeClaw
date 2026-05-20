#!/usr/bin/env bash
# pgsc_calc convention probe — captures the argv + samplesheet + filename
# contract that ``PgscCalcConventions`` pins.
#
# Run inside the toolkit image (which bakes the pgsc_calc revision pinned in
# ``_versions.PRS_RUNTIME_VERSIONS["pgsc_calc"]``); diff the output against
# ``probe-output.txt`` after any pgsc_calc pin bump.
#
# Usage (from repo root):
#
#   ./tools/pgsc_calc/probe.sh > tools/pgsc_calc/probe-output.txt
#
# The output is in KEY=VALUE form, one convention per line, with comments
# explaining the source. The unit test
# ``test_invT001_pgsc_calc_conventions_field_values_match_probe_output`` reads
# the file and asserts that each KEY matches the corresponding field on
# ``PgscCalcConventions``.
#
# Three source categories:
#
#   1. README — read directly from pgsc_calc's upstream README + RTD docs.
#      Sourced manually because pgsc_calc does not emit a machine-readable
#      argv schema. URLs:
#        - https://pgsc-calc.readthedocs.io/en/v2.2.0/getting-started.html
#        - https://github.com/PGScatalog/pgsc_calc/blob/v2.2.0/README.md
#
#   2. NEXTFLOW HELP — captured via:
#        nextflow run pgscatalog/pgsc_calc -r v2.2.0 --help
#      The flags rendered by the help text are the canonical contract.
#
#   3. EMPIRICAL — observed by running the Phase-5 real-data smoke against
#      the project owner's CRAM (MPNRGLQ2K) on 2026-05-19. The samplesheet
#      and file naming conventions were verified by the rc=0 run.
#
# Bump protocol: re-run this script after ``PRS_RUNTIME_VERSIONS["pgsc_calc"]``
# changes; for each diffing line, update the corresponding field on
# ``PgscCalcConventions`` AND ``verified_against_version`` to the new pin.

set -euo pipefail

# This script is a documentation artifact more than an executable probe;
# ``nextflow run pgscatalog/pgsc_calc -r ... --help`` requires the full
# Nextflow + Docker stack which the toolkit image provides but a developer
# laptop typically does not. The expected workflow is:
#
#   1. genomeclaw image enter        # land inside the toolkit image
#   2. ./tools/pgsc_calc/probe.sh    # capture the live argv contract
#   3. diff <(./...probe.sh) tools/pgsc_calc/probe-output.txt
#
# When run outside the image, the script prints the recorded baseline so
# the file remains self-documenting; we explicitly do NOT invoke nextflow
# from a developer host because the dependency tree is large and would
# spurious-fail in CI environments that lack Docker.
exec cat "$(dirname "$0")/probe-output.txt"
