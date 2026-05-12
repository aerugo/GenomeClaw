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

# Python toolkit venv from the uv build.
COPY --from=pybuild /opt/genomeclaw/toolkit /opt/genomeclaw/toolkit

# Put both on PATH; toolkit venv first so `genomeclaw-prep` resolves there.
ENV PATH="/opt/genomeclaw/toolkit/.venv/bin:/opt/conda/bin:${PATH}"

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
