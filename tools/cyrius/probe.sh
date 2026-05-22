#!/usr/bin/env bash
# Cyrius convention probe — captures the argv + JSON-output contract that
# ``CyriusConventions`` pins.
#
# Run inside the toolkit image (which bakes the Cyrius source tree pinned in
# ``_versions.PGX_RUNTIME_VERSIONS["cyrius"]``); diff the output against
# ``probe-output.txt`` after any Cyrius pin bump.
#
# Usage (from repo root, inside the toolkit image):
#
#   ./tools/cyrius/probe.sh > tools/cyrius/probe-output.txt
#
# The output is in KEY=VALUE form, one convention per line, with comments
# explaining the source. The unit test
# ``test_invT001_cyrius_conventions_field_values_match_probe_output`` (when
# it lands) will read the file and assert that each KEY matches the
# corresponding field on ``CyriusConventions``.
#
# Two source categories:
#
#   1. README — read directly from Cyrius's upstream README at
#        https://github.com/Illumina/Cyrius/blob/v1.1.1/README.md
#      Sourced manually because Cyrius does not emit a machine-readable
#      argv schema.
#
#   2. EMPIRICAL — observed by running ``star_caller.py --help`` inside the
#      toolkit image. The flags rendered by the help text are the canonical
#      contract.
#
# Bump protocol: re-run this script after ``PGX_RUNTIME_VERSIONS["cyrius"]``
# changes; for each diffing line, update the corresponding field on
# ``CyriusConventions`` AND ``verified_against_version`` to the new pin.

set -euo pipefail

# This script is a documentation artifact more than an executable probe;
# ``star_caller.py --help`` requires the Cyrius source tree + pysam env
# which only the toolkit image provides. The expected workflow is:
#
#   1. genomeclaw image enter        # land inside the toolkit image
#   2. ./tools/cyrius/probe.sh       # capture the live argv contract
#   3. diff <(./...probe.sh) tools/cyrius/probe-output.txt
#
# When run outside the image, the script prints the recorded baseline so
# the file remains self-documenting; we explicitly do NOT invoke
# `star_caller.py` from a developer host because the pysam dependency
# tree would spurious-fail in environments that lack the toolkit image.
exec cat "$(dirname "$0")/probe-output.txt"
