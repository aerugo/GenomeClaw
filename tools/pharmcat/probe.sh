#!/usr/bin/env bash
# PharmCAT convention probe — captures the argv + outside-call TSV +
# output JSON contract that ``PharmCATConventions`` pins.
#
# Run inside the toolkit image (which bakes PharmCAT v3.2.0 via Stage
# `pharmcat`); diff the output against ``probe-output.txt`` after any
# PharmCAT pin bump.
#
# Usage (from repo root, inside the toolkit image):
#
#   ./tools/pharmcat/probe.sh > tools/pharmcat/probe-output.txt
#
# Three source captures:
#
#   1. ``pharmcat_vcf_preprocessor --help`` — the Python preprocessor's
#      argv contract.
#   2. ``java -jar /opt/pharmcat/pharmcat.jar --help`` — the JAR's argv
#      contract (this is where the ``-po`` outside-call flag lives).
#   3. Reference: outside-call TSV format from
#      docs/using/Outside-Call-Format.md at the v3.2.0 tag.

set -euo pipefail

# This script is a documentation artifact — the actual argv contract
# is captured into the per-stage *-help.txt files in this directory.
# Pin-bump protocol:
#   1. Rebuild the toolkit image with the new PharmCAT release.
#   2. Re-run this script inside the rebuilt image.
#   3. Diff against probe-output.txt; for each diff, update the
#      corresponding field on PharmCATConventions AND bump
#      ``verified_against_version`` to the new pin.
exec cat "$(dirname "$0")/probe-output.txt"
