# syntax=docker/dockerfile:1.7
#
# genomeclaw/toolkit — host-side image bundling the bioinformatics binaries
# alongside the Python toolkit (`genomeclaw-prep` + `genomeclaw-service`).
#
# Bioinformatics tools (bcftools, mosdepth, samtools, htslib) come from
# bioconda via micromamba. The Python toolkit is installed with uv into a
# separate venv layered on top, so dependency upgrades do not invalidate the
# bioinformatics layer.
#
# Heavy reference data (VEP cache, AlphaMissense, gnomAD, PGS Catalog
# weights) is NEVER baked in. It is bind-mounted at run time from the host:
#
#   docker run --rm \
#     -v /mnt/genomeclaw/raw:/mnt/genomeclaw/raw:ro \
#     -v /mnt/genomeclaw/reference:/mnt/genomeclaw/reference:ro \
#     -v /mnt/genomeclaw/derived:/mnt/genomeclaw/derived:rw \
#     genomeclaw/toolkit:<tag> genomeclaw-prep ...
#
# Architecture: see docs/reference/architecture.md, "Host-side packaging".

ARG MAMBA_TAG=2.0.5
ARG UV_TAG=0.6.10
ARG BCFTOOLS_VERSION=1.21
ARG MOSDEPTH_VERSION=0.3.10
ARG SAMTOOLS_VERSION=1.21
ARG HTSLIB_VERSION=1.21
ARG VCFANNO_VERSION=0.3.5
ARG VEP_VERSION=114.1
# LOFTEE: konradjk/loftee. The ``master`` branch is GRCh37-era; the
# ``grch38`` branch is the canonical GRCh38 build (Phase 4D ships
# GRCh38 only — Q5 of phase-4.md).
ARG LOFTEE_REPO=https://github.com/konradjk/loftee.git
ARG LOFTEE_REF=grch38
# Ensembl/VEP_plugins: master is rolling-latest. Pin to the
# release/<vep-major> branch that ships alongside the VEP release in
# Stage 1 to keep plugin code + VEP code in sync. The runtime
# ``--dir_plugins`` flag resolves these in /opt/vep/.vep/Plugins/.
ARG VEP_PLUGINS_REPO=https://github.com/Ensembl/VEP_plugins.git
ARG VEP_PLUGINS_REF=release/114

# ---------------------------------------------------------------------------
# Stage 1 — bioinformatics binaries via bioconda.
# ---------------------------------------------------------------------------
FROM mambaorg/micromamba:${MAMBA_TAG} AS bio
ARG BCFTOOLS_VERSION
ARG MOSDEPTH_VERSION
ARG SAMTOOLS_VERSION
ARG HTSLIB_VERSION
ARG VCFANNO_VERSION
USER root
RUN micromamba install -y -n base \
        -c conda-forge -c bioconda \
        "bcftools=${BCFTOOLS_VERSION}" \
        "mosdepth=${MOSDEPTH_VERSION}" \
        "samtools=${SAMTOOLS_VERSION}" \
        "htslib=${HTSLIB_VERSION}" \
        "vcfanno=${VCFANNO_VERSION}" \
    && micromamba clean -a -y

# ---------------------------------------------------------------------------
# Stage 1a — VEP in its own micromamba env. VEP's perl-bioperl deps pull
# in perl-bio-samtools, which pins samtools < 1.0 — that conflicts with
# our samtools=1.21 in Stage 1. Isolating VEP in /opt/conda-vep keeps
# both versions installable; the runtime image puts /opt/conda/bin
# first on PATH so the toolkit's samtools/bcftools/etc. resolve to the
# 1.x versions, and /opt/conda-vep/bin is appended for VEP itself.
# ---------------------------------------------------------------------------
FROM mambaorg/micromamba:${MAMBA_TAG} AS vep
ARG VEP_VERSION
USER root
# ``perl-bioperl`` is **not** pulled in transitively by ``ensembl-vep`` —
# VEP itself uses ``Bio::EnsEMBL::*``, not ``Bio::Perl``. The LOFTEE
# plugin (``LoF.pm`` line 46) explicitly ``use Bio::Perl;`` so without
# the explicit install LOFTEE silently fails to compile at runtime and
# every variant's ``loftee_lof`` column ends up NULL. Documented as the
# 2026-05-14 real-data smoke regression — see
# ``tests/integration/test_vep_loftee_plugin.py``.
#
# ``perl-bio-bigfile`` provides ``Bio::DB::BigFile`` — used by LOFTEE's
# ``gerp_dist.pl`` helper (loaded by LoF.pm via ``do`` at runtime) to
# read the bigwig GERP conservation file. ``perl -c LoF.pm`` does NOT
# recurse into ``do``-loaded files, so the missing dep hid behind a
# passing LoF.pm syntax check; the 2026-05-15 real-data smoke surfaced
# it with another full set of NULL ``loftee_lof`` columns. The
# ``test_gerp_dist_helper_compiles_with_vep_perl_inside_image`` test
# guards against re-introducing the gap.
#
# Workaround for a bioconda packaging quirk: ``perl-bioperl-core`` 1.7.8
# ships ``lib/perl5/site_perl/BioPerl.pm`` (a different module) but NOT
# ``Bio/Perl.pm`` — the convenience wrapper LOFTEE's ``use Bio::Perl;``
# expects. LoF.pm has the bare ``use`` but **no callsite** for any
# Bio::Perl function (verified 2026-05-14 via ``grep Bio::Perl`` —
# exactly one hit in the entire plugin). So an empty package shim at
# ``Bio/Perl.pm`` satisfies the ``use`` statement without any runtime
# difference. If LOFTEE ever adds a real ``Bio::Perl::foo()`` call this
# shim will surface as ``Can't locate object method "foo" via package
# Bio::Perl`` and we switch to ``cpanm Bio::Perl`` here.
RUN micromamba create -y -p /opt/conda-vep \
        -c conda-forge -c bioconda \
        "ensembl-vep=${VEP_VERSION}" \
        perl-bioperl \
        perl-bio-bigfile \
    && micromamba clean -a -y \
    && printf 'package Bio::Perl;\nuse strict;\nuse warnings;\n# Empty shim — see Dockerfile comment.\n1;\n' \
       > /opt/conda-vep/lib/perl5/site_perl/Bio/Perl.pm

# ---------------------------------------------------------------------------
# Stage 1b — VEP plugins (LOFTEE + Ensembl/VEP_plugins) git-cloned in
# a separate stage so the runtime image can ``COPY --from=plugins``
# without dragging git's working-tree metadata. Plugin **code** lives
# in the image; plugin **data** (AlphaMissense / SpliceAI scores,
# LOFTEE human_ancestor.fa) is bind-mounted from
# ``reference/vep_cache/Plugins/`` at run time per Q3 of phase-4.md.
# ---------------------------------------------------------------------------
FROM debian:stable-slim AS vep-plugins
ARG LOFTEE_REPO
ARG LOFTEE_REF
ARG VEP_PLUGINS_REPO
ARG VEP_PLUGINS_REF
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /opt/vep/.vep/Plugins \
    && git clone --depth 1 --branch "${LOFTEE_REF}" "${LOFTEE_REPO}" /tmp/loftee \
    && cp -R /tmp/loftee/. /opt/vep/.vep/Plugins/ \
    && git clone --depth 1 --branch "${VEP_PLUGINS_REF}" "${VEP_PLUGINS_REPO}" /tmp/vep_plugins \
    && cp -R /tmp/vep_plugins/. /opt/vep/.vep/Plugins/ \
    && rm -rf /tmp/loftee /tmp/vep_plugins /opt/vep/.vep/Plugins/.git

# ---------------------------------------------------------------------------
# Stage 2 — Python toolkit installed into a uv-managed venv.
# ---------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:${UV_TAG} AS uv-bin

FROM python:3.11-slim AS pybuild
COPY --from=uv-bin /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1
WORKDIR /opt/genomeclaw/toolkit
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
# Include dev deps so the in-image test runner (pytest + pytest-httpserver +
# ruff) is available. The toolkit image is the host-side dev/CI image; the
# `INV-D002` "no bioinformatics binaries in the sandbox" rule applies only
# to the Phase-5 sandbox image, not this one.
RUN uv sync --frozen

# ---------------------------------------------------------------------------
# Stage 3 — runtime image.
#
# Base must match the pybuild stage's Python so the venv's interpreter
# symlinks (`/opt/genomeclaw/toolkit/.venv/bin/python` -> /usr/local/bin/python3)
# resolve in the runtime layer.
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime
LABEL org.opencontainers.image.title="genomeclaw/toolkit"
LABEL org.opencontainers.image.source="https://github.com/aerugo/GenomeClaw"
LABEL org.opencontainers.image.licenses="Apache-2.0"

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        e2fsprogs \
        tini \
    && rm -rf /var/lib/apt/lists/*

# Bioinformatics binaries from the micromamba env.
COPY --from=bio /opt/conda /opt/conda

# VEP from its isolated env (see Stage 1a comment above for why VEP
# can't co-habit /opt/conda — its perl-bioperl deps pin samtools < 1).
COPY --from=vep /opt/conda-vep /opt/conda-vep

# VEP plugins (LOFTEE + Ensembl/VEP_plugins). The plugin code is in the
# image at /opt/vep/.vep/Plugins/. Plugin **data** (AlphaMissense /
# SpliceAI scores, LOFTEE human_ancestor.fa, etc.) lives on the
# bind-mounted reference/vep_cache/Plugins/ volume per Q3.
COPY --from=vep-plugins /opt/vep /opt/vep

# Python toolkit venv from the uv build.
COPY --from=pybuild /opt/genomeclaw/toolkit /opt/genomeclaw/toolkit

# Put everything on PATH; toolkit venv first so ``genomeclaw`` resolves
# there. /opt/conda/bin is next so the project-pinned bcftools /
# mosdepth / samtools / htslib / vcfanno take priority over VEP's
# bundled versions. /opt/conda-vep/bin is last so ``vep`` resolves
# but doesn't shadow the rest.
ENV PATH="/opt/genomeclaw/toolkit/.venv/bin:/opt/conda/bin:/opt/conda-vep/bin:${PATH}"

# VEP's perl interpreter (/opt/conda-vep/bin/perl) has its @INC default
# pointing at /opt/conda/lib/perl5/... (the project-pinned env's perl
# tree, NOT its own), so ``vep --help`` fails with "Can't locate DBI.pm"
# unless we steer perl back to /opt/conda-vep's module tree. Setting
# PERL5LIB at the image level avoids forcing every caller to source
# micromamba's activate script. The order matters: VEP's bundled
# modules come first, then DBI / BioPerl / etc. from the conda env.
ENV PERL5LIB="/opt/conda-vep/share/ensembl-vep-114.1-0:/opt/conda-vep/share/ensembl-vep-114.1-0/modules:/opt/conda-vep/lib/perl5/5.32/site_perl:/opt/conda-vep/lib/perl5/site_perl:/opt/conda-vep/lib/perl5/5.32/vendor_perl:/opt/conda-vep/lib/perl5/vendor_perl:/opt/conda-vep/lib/perl5/5.32/core_perl:/opt/conda-vep/lib/perl5/core_perl"

# Mount points for the on-disk layout that architecture.md documents.
# `scratch/` is the ephemeral tier for temp / sort-temp / DuckDB spill /
# Nextflow `work/`. Nothing inside it is authoritative; orchestrators
# write into per-step subdirs and clean up on exit.
RUN mkdir -p /mnt/genomeclaw/raw /mnt/genomeclaw/reference \
             /mnt/genomeclaw/derived /mnt/genomeclaw/scratch

# Non-root user. Host bind-mounts work as long as the host UID matches; the
# shim under bin/genomeclaw-prep passes --user $(id -u):$(id -g) to keep
# derived/ files owned by the invoking user.
RUN groupadd --system --gid 1000 genomeclaw \
    && useradd --system --uid 1000 --gid genomeclaw --home-dir /home/genomeclaw \
        --create-home --shell /usr/sbin/nologin genomeclaw \
    && chown -R genomeclaw:genomeclaw /mnt/genomeclaw

USER genomeclaw
WORKDIR /work

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["genomeclaw-prep", "--help"]
