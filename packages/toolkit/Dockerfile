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
# Cyrius: Illumina's CYP2D6 star-allele caller. NOT packaged on bioconda
# (verified 2026-05-22 via `mamba search -c bioconda cyrius` against the
# phase6 image — "No entries matching cyrius found"). Cloned from
# github.com/Illumina/Cyrius at the v<X> tag via Stage `cyrius`. Single
# source of truth for the pin: src/genomeclaw_toolkit/prep/_versions.py
# ``PGX_RUNTIME_VERSIONS``. CLI entrypoint is ``star_caller.py`` per
# ``CyriusConventions``; Python deps (pysam, numpy, scipy, statsmodels)
# install into Stage `bio`'s micromamba env.
ARG CYRIUS_REPO=https://github.com/Illumina/Cyrius.git
ARG CYRIUS_REF=v1.1.1
# PharmCAT: PharmGKB's PGx recommendation engine. NOT packaged on bioconda
# (verified 2026-05-22). Distributed as a `pharmcat-pipeline-X.Y.Z.tar.gz`
# GitHub-releases artifact bundling the Python preprocessor + JAR. Single
# source of truth for the pin: src/genomeclaw_toolkit/prep/_versions.py
# ``PGX_RUNTIME_VERSIONS``. Entrypoint is ``pharmcat_pipeline`` per
# ``PharmCATConventions``.
ARG PHARMCAT_VERSION=3.2.0
ARG PHARMCAT_RELEASE_URL=https://github.com/PharmGKB/PharmCAT/releases/download/v3.2.0/pharmcat-pipeline-3.2.0.tar.gz
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
# PRS Runtime Bootstrap Phase 1 — Nextflow + JRE 17 + mamba + pre-warmed
# pgsc_calc source. Pgsc_calc requires Nextflow ≥ 23.10.0; we pin to a
# current stable LTS. JRE 17 is Nextflow's minimum. Mamba is required by
# `pgsc_calc -profile conda` for per-process env materialisation. Single
# source of truth for pins: src/genomeclaw_toolkit/prep/_versions.py
# ``PRS_RUNTIME_VERSIONS``.
ARG NEXTFLOW_VERSION=24.10.0
ARG PGSC_CALC_VERSION=v2.2.0
ARG JRE_VERSION=17

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
# Cyrius's runtime Python deps (pysam, numpy, scipy, statsmodels) live in
# this env so `/opt/conda/bin/python` (which Stage `cyrius` re-points the
# `star_caller.py` shebang at) can resolve them. The Cyrius source tree
# itself ships via Stage `cyrius`.
RUN micromamba install -y -n base \
        -c conda-forge -c bioconda \
        "bcftools=${BCFTOOLS_VERSION}" \
        "mosdepth=${MOSDEPTH_VERSION}" \
        "samtools=${SAMTOOLS_VERSION}" \
        "htslib=${HTSLIB_VERSION}" \
        "vcfanno=${VCFANNO_VERSION}" \
        "pysam" \
        "numpy" \
        "scipy" \
        "statsmodels" \
        "pandas>=2.1.3" \
        "colorama>=0.4.6" \
        "packaging>=24.1" \
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
# Stage `cyrius` — clone Illumina/Cyrius at the pinned tag into /opt/cyrius.
#
# Cyrius is NOT on bioconda (verified 2026-05-22). Cloning at a pinned tag
# from github.com/Illumina/Cyrius mirrors the LOFTEE pattern in
# Stage `vep-plugins` above. The runtime stage copies /opt/cyrius and adds
# it to PATH; the `star_caller.py` shebang is re-pointed at
# `/opt/conda/bin/python` so it resolves to Stage `bio`'s pysam-equipped
# env regardless of which other Python interpreters precede it on PATH.
# ---------------------------------------------------------------------------
FROM debian:stable-slim AS cyrius
ARG CYRIUS_REPO
ARG CYRIUS_REF
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch "${CYRIUS_REF}" "${CYRIUS_REPO}" /opt/cyrius \
    && rm -rf /opt/cyrius/.git \
    && chmod +x /opt/cyrius/star_caller.py \
    && sed -i '1s|^#!.*python.*$|#!/opt/conda/bin/python|' /opt/cyrius/star_caller.py

# ---------------------------------------------------------------------------
# Stage `pharmcat` — download + extract PharmCAT's pipeline release tarball.
#
# PharmCAT is NOT on bioconda (verified 2026-05-22). v3 ships as a tarball
# from GitHub releases bundling the Python preprocessor (`pharmcat_pipeline`)
# + the JAR (`pharmcat-X.Y.Z-all.jar`). The wrapper invokes the Python
# entrypoint per ``PharmCATConventions.entrypoint``. Runtime stage COPYs
# /opt/pharmcat and adds it to PATH; the entrypoint is a Python script that
# the conda env's `python` will resolve (no shebang rewrite needed — the
# upstream script uses `/usr/bin/env python3`, and the conda env injects
# a python3 first on PATH inside the runtime stage).
# ---------------------------------------------------------------------------
FROM debian:stable-slim AS pharmcat
ARG PHARMCAT_RELEASE_URL
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /opt/pharmcat \
    && curl -fsSL "${PHARMCAT_RELEASE_URL}" -o /tmp/pharmcat-pipeline.tar.gz \
    && tar -xzf /tmp/pharmcat-pipeline.tar.gz -C /opt/pharmcat \
    && rm /tmp/pharmcat-pipeline.tar.gz \
    && chmod +x /opt/pharmcat/pharmcat /opt/pharmcat/pharmcat_pipeline /opt/pharmcat/pharmcat_vcf_preprocessor \
    && sed -i '1s|^#!.*python.*$|#!/opt/conda/bin/python3|' \
        /opt/pharmcat/pharmcat_pipeline /opt/pharmcat/pharmcat_vcf_preprocessor

# ---------------------------------------------------------------------------
# Stage prs-runtime — Nextflow + JRE 17 + mamba in an isolated micromamba env
# (/opt/conda-prs), plus the pre-warmed `pgsc_calc` pipeline source at
# /opt/pgsc_calc/. Same isolation pattern as Stage `vep` — keeps the prs
# runtime layer independently cacheable and avoids polluting /opt/conda
# with openjdk/mamba/nextflow (the bio env's bcftools/samtools/htslib stays
# untouched on a Nextflow pin bump).
#
# Why these three pieces:
# - Nextflow: the orchestrator for pgsc_calc (Nextflow DSL2 pipeline).
# - JRE 17: Nextflow's runtime; required by Nextflow ≥ 24.x.
# - mamba: shelled out to by `pgsc_calc -profile conda` to materialise
#   per-process scoring envs (plink2, plink, R + Bioconductor) at first
#   user run into $NXF_CONDA_CACHEDIR on the bind-mounted reference
#   volume. The plink/R/Bioconductor deps are NOT baked into the image —
#   they materialise once + cache forever on the volume, governed by
#   `INV-R001` (rebuildable from `Dockerfile + pinned pgsc_calc release`).
#
# Pre-warming: `nextflow pull pgscatalog/pgsc_calc -r <pin>` runs at image-
# build time so the pipeline source is on-disk at /opt/pgsc_calc/, making
# the first user invocation offline-capable and the image deterministic
# from its hash.
# ---------------------------------------------------------------------------
FROM mambaorg/micromamba:${MAMBA_TAG} AS prs-runtime
ARG NEXTFLOW_VERSION
ARG PGSC_CALC_VERSION
ARG JRE_VERSION
USER root
# JDK 17 + mamba into an isolated env at /opt/conda-prs. Same pattern as
# /opt/conda-vep (Stage vep) — avoids pinning openjdk/mamba into the bio
# env where it could conflict with future bcftools/htslib upgrades.
RUN micromamba create -y -p /opt/conda-prs \
        -c conda-forge \
        "openjdk=${JRE_VERSION}" \
        "mamba" \
    && micromamba clean -a -y

# PATH + JAVA_HOME updates BEFORE the Nextflow installer + pull RUNs.
# The get.nextflow.io install script verifies a `java` binary is reachable
# at install time and aborts with rc=1 if it isn't, even before downloading
# the JAR (verified empirically 2026-05-17 — failed first build with
# PATH update positioned after the install).
ENV JAVA_HOME=/opt/conda-prs
ENV PATH="/opt/conda-prs/bin:${PATH}"
ENV NXF_VER=${NEXTFLOW_VERSION}

# Nextflow CLI via the official installer. Pinned via NXF_VER env so the
# installer fetches the exact version. The resulting `nextflow` binary
# lands in /opt/conda-prs/bin so it's discoverable on PATH alongside JDK
# + mamba from the same env.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://get.nextflow.io | bash \
    && mv nextflow /opt/conda-prs/bin/nextflow \
    && chmod +x /opt/conda-prs/bin/nextflow

# Pre-warm BOTH the Nextflow framework JAR + the pgsc_calc pipeline assets.
# NXF_HOME points at the canonical /opt/nextflow bake-in path so the layout
# becomes /opt/nextflow/{framework,assets}/. The same dir surfaces as
# /opt/pgsc_calc (canonical bake-in path probed by `host doctor`'s
# prs_runtime_ready check). `chmod a+rwX` makes the cache usable by the
# non-root genomeclaw user at runtime — Nextflow writes lock files +
# session metadata in $NXF_HOME during a run, so the cache cannot be
# read-only without an entrypoint-side state-dir indirection.
ENV NXF_HOME=/opt/nextflow
RUN nextflow pull pgscatalog/pgsc_calc -r ${PGSC_CALC_VERSION} \
    && cp -r ${NXF_HOME}/assets/pgscatalog/pgsc_calc /opt/pgsc_calc \
    && chmod -R a+rwX /opt/nextflow /opt/pgsc_calc

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

# Docker CLI for DooD (Docker-out-of-Docker) — required by `pgsc_calc
# -profile docker`. Real-data smoke 2026-05-17 surfaced that pgsc_calc
# v2.2.0's conda env definitions pin ``plink2 2.0a5.10`` which is
# unavailable on linux-aarch64 (conda-forge ships it only for linux-64).
# The conda/mamba profiles fail with "Could not solve for environment
# specs" on arm64 hosts. The `-profile docker` path uses pgscatalog/*
# pre-baked images (multi-arch including arm64) and skips conda env
# materialisation entirely — much faster + works on arm64.
#
# Trade-off vs the spec's image-or-volume boundary: the container needs
# the host Docker socket bind-mounted (`-v /var/run/docker.sock:/var/run/
# docker.sock`) so the nested `docker run` calls spawn sibling containers
# via the host's Docker daemon. For the single-user PoC this is
# acceptable; architectural purity (Singularity profile, or arm64-
# friendly conda envs in a future pgsc_calc release) is a follow-up.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gnupg \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && chmod a+r /etc/apt/keyrings/docker.gpg \
    && . /etc/os-release \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian ${VERSION_CODENAME} stable" \
        | tee /etc/apt/sources.list.d/docker.list > /dev/null \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli \
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

# Cyrius — Illumina's CYP2D6 star-allele caller. The script tree lives
# at /opt/cyrius/. star_caller.py's shebang is re-pointed at
# /opt/conda/bin/python so it picks up Stage `bio`'s pysam env regardless
# of which Python interpreters PATH resolves first. Per Slice D (MVP
# Phase 6); CyriusConventions.entrypoint pins the filename.
COPY --from=cyrius /opt/cyrius /opt/cyrius

# PharmCAT — PharmGKB's PGx recommendation engine. The pipeline tarball
# extracts to /opt/pharmcat/ with `pharmcat_pipeline` (Python) +
# `pharmcat-X.Y.Z-all.jar`. Per Slice D' (MVP Phase 6);
# PharmCATConventions.entrypoint pins the filename.
COPY --from=pharmcat /opt/pharmcat /opt/pharmcat

# PRS runtime (Stage prs-runtime): nextflow + JRE 17 + mamba isolated at
# /opt/conda-prs/ + the Nextflow framework + pgsc_calc assets cache at
# /opt/nextflow/ + the canonical pgsc_calc pipeline-source marker at
# /opt/pgsc_calc/. The conda env is isolated for the same reason as
# /opt/conda-vep — it pins openjdk which we don't want pinned in /opt/conda
# alongside the bio binaries. /opt/nextflow is set as the runtime NXF_HOME
# default below so the launcher finds the pre-warmed JAR + assets without
# a first-run download tax.
COPY --from=prs-runtime /opt/conda-prs /opt/conda-prs
COPY --from=prs-runtime /opt/nextflow /opt/nextflow
COPY --from=prs-runtime /opt/pgsc_calc /opt/pgsc_calc

# Default NXF_HOME points at the pre-warmed cache. The shim can override
# via `-e NXF_HOME=/mnt/genomeclaw/reference/nextflow-cache` to share the
# cache across container restarts on the bind-mounted reference volume.
ENV NXF_HOME=/opt/nextflow

# Python toolkit venv from the uv build.
COPY --from=pybuild /opt/genomeclaw/toolkit /opt/genomeclaw/toolkit

# Put everything on PATH; toolkit venv first so ``genomeclaw`` resolves
# there. /opt/conda/bin is next so the project-pinned bcftools /
# mosdepth / samtools / htslib / vcfanno take priority over VEP's
# bundled versions. /opt/conda-prs/bin carries nextflow / java / mamba —
# placed before /opt/conda-vep/bin so `mamba` from prs resolves before
# any (transitive) mamba VEP might pull in. /opt/conda-vep/bin is last
# so ``vep`` resolves but doesn't shadow the rest.
ENV PATH="/opt/genomeclaw/toolkit/.venv/bin:/opt/conda/bin:/opt/conda-prs/bin:/opt/conda-vep/bin:/opt/cyrius:/opt/pharmcat:${PATH}"

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
    && mkdir -p /work \
    && chown -R genomeclaw:genomeclaw /mnt/genomeclaw /work

USER genomeclaw
WORKDIR /work

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["genomeclaw-prep", "--help"]
