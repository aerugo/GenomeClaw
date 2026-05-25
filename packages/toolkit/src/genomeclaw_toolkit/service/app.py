"""``genomeclaw-service`` FastAPI app factory.

Phase 5 Slice A — wires the smallest read-only surface that proves the
host service architecture works end-to-end:

- Resolves ``derived_root/CURRENT`` at app construction time so the route
  handlers operate against a cached :class:`ActiveRun` snapshot.
- Exposes ``GET /v1/health`` returning the active run's id + schema
  version, or a 503 with a typed error body when the active run is
  unavailable / on a different schema.

`INV-D002`: this service is the *host-side* read-only surface; the
sandbox image (Phase 5 Slice C) reaches it via OpenShell's L7 proxy and
can only see paths the policy preset allows. `INV-P002`: every response
shape is pinned to a Pydantic model with ``extra="forbid"`` so a future
regression that widens a payload surfaces in the snapshot tests.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import os
import signal
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import FastAPI, Query
from fastapi import Path as FastAPIPath
from fastapi.responses import JSONResponse

from genomeclaw_toolkit.schemas import SCHEMA_VERSION
from genomeclaw_toolkit.schemas.evidence import EvidenceErrorResponse, EvidenceRecord
from genomeclaw_toolkit.schemas.finding import (
    Category,
    Finding,
    FindingErrorResponse,
    FindingsListResponse,
)
from genomeclaw_toolkit.schemas.gene import GeneErrorResponse, GeneResponse
from genomeclaw_toolkit.schemas.health import HealthErrorResponse, HealthResponse
from genomeclaw_toolkit.schemas.pgs import (
    PgsComputeRequest,
    PgsComputeTaskResponse,
    PgsErrorResponse,
    PgsListResponse,
    PgsListRow,
    PgsRowResponse,
)
from genomeclaw_toolkit.schemas.provenance import Provenance
from genomeclaw_toolkit.schemas.variant import (
    VariantDetail,
    VariantErrorResponse,
    VariantsListResponse,
    VariantSummary,
)
from genomeclaw_toolkit.service.pgs_compute_config import (
    PrsComputeConfigMalformedError,
    PrsComputeConfigMissingError,
    load_prs_compute_config,
)
from genomeclaw_toolkit.service.pgs_compute_orchestrator import (
    _real_compute_fn,
    _resolve_compute_enabled,
    cleanup_stale_running_tasks,
    create_pgs_compute_tasks_db_if_missing,
    enqueue_pgs_compute_task,
    pgs_compute_worker_lifespan,
    query_pgs_compute_task_status,
)
from genomeclaw_toolkit.service.store import (
    ActiveRun,
    InvalidEvidenceRefError,
    InvalidVariantKeyError,
    NoActiveRunError,
    SchemaVersionMismatchError,
    UnknownEvidenceKindError,
    load_active_run,
    load_provenance,
    query_finding_by_id,
    query_findings,
    query_gene,
    query_pgs_computed,
    query_pgs_computed_list,
    query_variant_by_key,
    query_variants,
    resolve_evidence,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

_LOG = logging.getLogger(__name__)


class _ActiveRunCache:
    """Mutable holder for the resolved :class:`ActiveRun` + last error.

    The FastAPI app reads from this on every request; ``SIGHUP`` triggers
    a re-resolve. Holding the cache as a small object (rather than module
    globals) keeps the app testable: each :func:`build_app` call gets its
    own cache.
    """

    def __init__(self) -> None:
        self.active: ActiveRun | None = None
        self.error: Exception | None = None

    def reload(self, *, derived_root: Path) -> None:
        try:
            self.active = load_active_run(
                derived_root=derived_root, expected_schema_version=SCHEMA_VERSION
            )
            self.error = None
        except (NoActiveRunError, SchemaVersionMismatchError) as exc:
            self.active = None
            self.error = exc


def _publish_host_roots_from_config(config: Any) -> None:
    """Set ``GENOMECLAW_HOST_ROOTS`` from the sidecar's host-form paths.

    :func:`prep._paths.as_sibling_mountable` requires this env var to
    validate paths bound for DooD-spawned siblings. The shim publishes it
    when the toolkit runs inside a container (``GENOMECLAW_DOOD=1``); the
    host service running outside the toolkit container has no such shim.
    Without this propagation the worker fails every compute with
    ``dood_path_error`` even though the sidecar paths are valid host-form.

    Idempotent: an operator-supplied ``GENOMECLAW_HOST_ROOTS`` is honoured
    in addition to the derived roots — the helper appends rather than
    overwrites. The derived roots are the four directories the sidecar
    paths live under (CRAM raw, reference, sidecar-declared work dir
    parent, and the active run's derived-root parent).
    """
    existing = os.environ.get("GENOMECLAW_HOST_ROOTS", "").strip()
    derived_roots: list[str] = []
    candidates = [
        config.cram_path.parent.parent,  # raw/
        config.reference_root,
        config.work_dir_root.parent,  # _scratch/
    ]
    for c in candidates:
        s = str(c)
        if s and s not in derived_roots and (not existing or s not in existing):
            derived_roots.append(s)
    if not derived_roots:
        return
    merged = existing + ":" + ":".join(derived_roots) if existing else ":".join(derived_roots)
    os.environ["GENOMECLAW_HOST_ROOTS"] = merged
    _LOG.info(
        "Published GENOMECLAW_HOST_ROOTS from sidecar: %s", merged
    )


def build_app(*, derived_root: Path) -> FastAPI:
    """Construct the FastAPI app bound to ``derived_root``.

    The resolver runs once here (so the app's first request doesn't pay
    the resolve cost) and again on ``SIGHUP``. Tests construct a fresh
    app per case via :class:`fastapi.testclient.TestClient`.

    Args:
        derived_root: path to the derived dir containing ``CURRENT`` +
            per-run subdirs. The active run's `variants.duckdb` is read
            from here.

    The earlier ``reference_dir`` parameter (Phase 6 Slice B) was removed
    in agent-research-and-synthesis Phase 1 — the host service no longer
    resolves curated-notes evidence kinds. Lifestyle calibration is now
    an agent-workspace concern (memory + reasoned research).
    """
    cache = _ActiveRunCache()
    cache.reload(derived_root=derived_root)

    @contextlib.asynccontextmanager
    async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
        """Spawn the E.3 PGS compute worker; cancel on shutdown.

        Reads ``prs_compute_config.json`` from the active run-dir. If
        present, binds the worker's ``compute_fn`` to
        :func:`_real_compute_fn` via :func:`functools.partial`. If missing
        or malformed, logs a clear WARNING + skips spawning the worker —
        the read routes still work; only the compute path is offline.

        If no active run is resolved (e.g. the host service is up but
        ``CURRENT`` is broken), the worker is not spawned — the
        ``/v1/health`` 503 path still serves the operator the diagnostic.
        """
        worker_ctx = None
        if cache.active is not None:
            run_dir = cache.active.run_dir
            db_path = run_dir / "pgs_compute_tasks.sqlite"
            create_pgs_compute_tasks_db_if_missing(db_path)
            # Phase 5: transition any `running` row left over from an
            # unclean prior shutdown to `failed:worker_restart:stale_running`
            # before the worker starts polling. Emits a WARNING per cleaned
            # row so the operator sees them on tail -f.
            cleaned = cleanup_stale_running_tasks(db_path)
            if cleaned:
                _LOG.warning(
                    "Cleaned %d stale-running PGS compute task(s) on startup",
                    len(cleaned),
                )
            # `compute_fn` resolution:
            #   - sidecar present + valid     → bind _real_compute_fn with the config.
            #   - sidecar missing / malformed → bind a raising stub so the worker's
            #                                   normal except path marks tasks
            #                                   `failed:prs_compute_config_{missing,malformed}`.
            #
            # Before this change (investigate-pgs-compute-ack-without-row plan,
            # 2026-05-25): missing-sidecar left compute_fn=None, which the
            # orchestrator silently fell through to a no-op compute that
            # marked every task `done` without writing a pgs_scores row. The
            # agent then saw `done` and a no-result, called it "the compute
            # task reached done, but the result endpoint did not return a
            # percentile" — surfaced 5 times across two demo sessions on
            # PGS000014 + PGS000334.
            compute_fn = None
            try:
                prs_config = load_prs_compute_config(run_dir)
            except PrsComputeConfigMissingError as exc:
                _LOG.warning(
                    "prs_compute_config.json missing; PGS compute worker will "
                    "transition every enqueued task to failed:prs_compute_config_missing "
                    "so the agent gets a clear actionable signal. %s",
                    exc,
                )
                # Capture in a closure so the worker raises the right
                # error class on each compute attempt.
                _missing_exc = exc
                async def _raise_missing(_task):
                    raise _missing_exc
                compute_fn = _raise_missing
            except PrsComputeConfigMalformedError as exc:
                _LOG.warning(
                    "prs_compute_config.json malformed; PGS compute worker will "
                    "transition every enqueued task to failed:prs_compute_config_malformed "
                    "so the agent gets a clear actionable signal. %s",
                    exc,
                )
                _malformed_exc = exc
                async def _raise_malformed(_task):
                    raise _malformed_exc
                compute_fn = _raise_malformed
            else:
                # Phase 4 + 2026-05-23 fix: propagate the sidecar's host-form
                # paths to ``GENOMECLAW_HOST_ROOTS`` so
                # :func:`prep._paths.as_sibling_mountable` accepts them. The
                # shim normally publishes this env var when ``GENOMECLAW_DOOD=1``;
                # the host service running outside the toolkit container has
                # no such shim. Without this propagation the worker fails
                # every compute with ``dood_path_error`` even though the
                # sidecar paths are perfectly valid host-form paths.
                _publish_host_roots_from_config(prs_config)
                compute_fn = functools.partial(
                    _real_compute_fn,
                    config=prs_config,
                    run_dir=run_dir,
                    # Phase 2 (worker-self-sufficient-compute): thread the
                    # kill-switch fn so _ensure_scorefile_staged can gate
                    # PGS Catalog egress at fetch-decision time (not at
                    # startup). Re-evaluated on each compute so a mid-run
                    # flip takes effect immediately.
                    compute_enabled_fn=_resolve_compute_enabled,
                )
            worker_ctx = pgs_compute_worker_lifespan(db_path, compute_fn=compute_fn)
            await worker_ctx.__aenter__()
        try:
            yield
        finally:
            if worker_ctx is not None:
                with contextlib.suppress(asyncio.CancelledError):
                    await worker_ctx.__aexit__(None, None, None)

    app = FastAPI(
        title="genomeclaw-service",
        version="v0.2",
        docs_url=None,  # No interactive docs surface — INV-P002 minimal-sufficient.
        redoc_url=None,
        lifespan=_lifespan,
    )

    # SIGHUP → re-resolve. Skipped on platforms without SIGHUP (Windows);
    # the host service only ships on POSIX so the guard is defensive.
    if hasattr(signal, "SIGHUP"):

        def _handle_sighup(_signum: int, _frame: Any) -> None:
            cache.reload(derived_root=derived_root)

        # Signal handlers can only be installed on the main thread;
        # TestClient runs on the main thread but defensive for threaded
        # test runners.
        with contextlib.suppress(ValueError):
            signal.signal(signal.SIGHUP, _handle_sighup)

    @app.get("/v1/health")
    def health() -> JSONResponse:
        if cache.active is not None:
            payload = HealthResponse(
                schema_version=cache.active.schema_version,
                current_run_id=cache.active.run_id,
                sample_id=cache.active.sample_id,
            )
            return JSONResponse(status_code=200, content=payload.model_dump())

        if isinstance(cache.error, SchemaVersionMismatchError):
            error = HealthErrorResponse(status="schema_version_mismatch", detail=str(cache.error))
        else:
            # NoActiveRunError or anything unexpected — surface as
            # "no active run" with the underlying message.
            detail = (
                str(cache.error)
                if cache.error
                else (
                    "no CURRENT symlink under the derived root; run `genomeclaw pipeline run` first"
                )
            )
            error = HealthErrorResponse(status="no_active_run", detail=detail)

        return JSONResponse(status_code=503, content=error.model_dump())

    def _require_active_run() -> ActiveRun | JSONResponse:
        """Return the cached active run, or a 503 JSONResponse for the route to bail with."""
        if cache.active is not None:
            return cache.active
        detail = str(cache.error) if cache.error else "no active run"
        return JSONResponse(
            status_code=503,
            content=VariantErrorResponse(detail=detail).model_dump(),
        )

    @app.get("/v1/variants")
    def variants_list(
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> JSONResponse:
        active = _require_active_run()
        if isinstance(active, JSONResponse):
            return active
        rows, total = query_variants(run_dir=active.run_dir, limit=limit, offset=offset)
        next_offset = offset + len(rows) if offset + len(rows) < total else None
        payload = VariantsListResponse(
            rows=[VariantSummary(**r) for r in rows],
            total=total,
            limit=limit,
            offset=offset,
            next_offset=next_offset,
        )
        return JSONResponse(status_code=200, content=payload.model_dump())

    @app.get("/v1/variants/{key}")
    def variant_by_key(key: Annotated[str, FastAPIPath(min_length=1)]) -> JSONResponse:
        active = _require_active_run()
        if isinstance(active, JSONResponse):
            return active
        try:
            row = query_variant_by_key(run_dir=active.run_dir, key=key)
        except InvalidVariantKeyError as exc:
            return JSONResponse(
                status_code=400,
                content=VariantErrorResponse(detail=str(exc)).model_dump(),
            )
        if row is None:
            return JSONResponse(
                status_code=404,
                content=VariantErrorResponse(
                    detail=f"no variant matches key {key!r} in the active run"
                ).model_dump(),
            )
        payload = VariantDetail(**row)
        return JSONResponse(status_code=200, content=payload.model_dump())

    @app.get("/v1/findings")
    def findings_list(
        category: Annotated[Category | None, Query()] = None,
        genes: Annotated[list[str] | None, Query()] = None,
        drugs: Annotated[list[str] | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 25,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> JSONResponse:
        active = _require_active_run()
        if isinstance(active, JSONResponse):
            return active
        rows, total = query_findings(
            run_dir=active.run_dir,
            category=category,
            genes=tuple(genes) if genes else None,
            drugs=tuple(drugs) if drugs else None,
            limit=limit,
            offset=offset,
        )
        next_offset = offset + len(rows) if offset + len(rows) < total else None
        payload = FindingsListResponse(
            rows=[Finding(**r) for r in rows],
            total=total,
            limit=limit,
            offset=offset,
            next_offset=next_offset,
        )
        return JSONResponse(status_code=200, content=payload.model_dump())

    @app.get("/v1/findings/{finding_id}")
    def finding_by_id(finding_id: Annotated[str, FastAPIPath(min_length=1)]) -> JSONResponse:
        active = _require_active_run()
        if isinstance(active, JSONResponse):
            return active
        row = query_finding_by_id(run_dir=active.run_dir, finding_id=finding_id)
        if row is None:
            return JSONResponse(
                status_code=404,
                content=FindingErrorResponse(
                    detail=f"no finding matches id {finding_id!r} in the active run"
                ).model_dump(),
            )
        payload = Finding(**row)
        return JSONResponse(status_code=200, content=payload.model_dump())

    @app.get("/v1/evidence/{ref:path}")
    def evidence(ref: Annotated[str, FastAPIPath(min_length=1)]) -> JSONResponse:
        active = _require_active_run()
        if isinstance(active, JSONResponse):
            return active
        try:
            record = resolve_evidence(run_dir=active.run_dir, ref=ref)
        except (InvalidEvidenceRefError, UnknownEvidenceKindError) as exc:
            return JSONResponse(
                status_code=400,
                content=EvidenceErrorResponse(detail=str(exc)).model_dump(),
            )
        if record is None:
            return JSONResponse(
                status_code=404,
                content=EvidenceErrorResponse(
                    detail=f"no evidence record matches ref {ref!r} in the active run"
                ).model_dump(),
            )
        payload = EvidenceRecord(**record)
        return JSONResponse(status_code=200, content=payload.model_dump())

    @app.get("/v1/provenance/{run_id}")
    def provenance(run_id: Annotated[str, FastAPIPath(min_length=1)]) -> JSONResponse:
        active = _require_active_run()
        if isinstance(active, JSONResponse):
            return active
        # Slice C ships single-run semantics: only the active run is
        # served. Historical-run support requires walking the derived/
        # tree + isolating reads to each run's manifest; deferred.
        if run_id != active.run_id:
            return JSONResponse(
                status_code=404,
                content=VariantErrorResponse(
                    detail=(
                        f"run-id {run_id!r} is not the active run "
                        f"({active.run_id!r}); only the active run's "
                        "provenance is exposed by this build"
                    )
                ).model_dump(),
            )
        raw = load_provenance(run_dir=active.run_dir)
        # Validate the on-disk trail through the Provenance model so a
        # malformed file surfaces as a typed error rather than passing
        # arbitrary JSON to the agent.
        payload = Provenance.model_validate(raw)
        return JSONResponse(status_code=200, content=payload.model_dump(mode="json"))

    @app.get("/v1/gene/{symbol}")
    def gene(symbol: Annotated[str, FastAPIPath(min_length=1)]) -> JSONResponse:
        active = _require_active_run()
        if isinstance(active, JSONResponse):
            return active
        aggregate = query_gene(run_dir=active.run_dir, symbol=symbol)
        if aggregate is None:
            return JSONResponse(
                status_code=404,
                content=GeneErrorResponse(
                    detail=f"no rows match gene symbol {symbol!r} in the active run"
                ).model_dump(),
            )
        payload = GeneResponse(
            gene=aggregate.canonical_symbol,
            n_variants_in_gene=aggregate.n_variants_in_gene,
            mean_depth=aggregate.mean_depth,
            low_coverage_exons=aggregate.low_coverage_exons,
            schema_version=active.schema_version,
        )
        return JSONResponse(status_code=200, content=payload.model_dump())

    # --- Phase 6 Slice E v2 — agent-driven PRS endpoints (Q8 v1.6) -----------
    # Four endpoints, all keyed by PGS Catalog ID, replacing the v1.5 single
    # `/v1/pgs/{trait}` lookup. Compute is async + agent-triggered; rationale
    # + alternatives considered persist per INV-A003.

    @app.get("/v1/pgs/computed")
    def pgs_computed_list() -> JSONResponse:
        active = _require_active_run()
        if isinstance(active, JSONResponse):
            return active
        rows, total = query_pgs_computed_list(run_dir=active.run_dir)
        payload = PgsListResponse(
            rows=[PgsListRow(**r) for r in rows],
            total=total,
        )
        return JSONResponse(status_code=200, content=payload.model_dump())

    @app.get("/v1/pgs/computed/{pgs_id}")
    def pgs_computed_get(pgs_id: Annotated[str, FastAPIPath(min_length=1)]) -> JSONResponse:
        active = _require_active_run()
        if isinstance(active, JSONResponse):
            return active
        row = query_pgs_computed(run_dir=active.run_dir, pgs_id=pgs_id)
        if row is None:
            return JSONResponse(
                status_code=404,
                content=PgsErrorResponse(
                    detail=f"no PGS matches id {pgs_id!r} in the active run"
                ).model_dump(),
            )
        payload = PgsRowResponse(**row)
        return JSONResponse(status_code=200, content=payload.model_dump())

    @app.post("/v1/pgs/compute", status_code=202)
    def pgs_compute_request(request: PgsComputeRequest) -> JSONResponse:
        active = _require_active_run()
        if isinstance(active, JSONResponse):
            return active
        task = enqueue_pgs_compute_task(
            active.run_dir / "pgs_compute_tasks.sqlite",
            pgs_id=request.pgs_id,
            trait_label=request.trait_label,
            rationale=request.rationale,
            requested_for_question=request.requested_for_question,
        )
        payload = PgsComputeTaskResponse(
            task_id=task.task_id,
            pgs_id=task.pgs_id,
            status=task.status,
            error=task.error,
        )
        return JSONResponse(status_code=202, content=payload.model_dump())

    @app.get("/v1/pgs/compute/{task_id}")
    def pgs_compute_status(task_id: Annotated[str, FastAPIPath(min_length=1)]) -> JSONResponse:
        active = _require_active_run()
        if isinstance(active, JSONResponse):
            return active
        task = query_pgs_compute_task_status(
            active.run_dir / "pgs_compute_tasks.sqlite", task_id=task_id
        )
        if task is None:
            return JSONResponse(
                status_code=404,
                content=PgsErrorResponse(
                    detail=f"no compute task matches id {task_id!r} in the active run"
                ).model_dump(),
            )
        payload = PgsComputeTaskResponse(
            task_id=task.task_id,
            pgs_id=task.pgs_id,
            status=task.status,
            error=task.error,
        )
        return JSONResponse(status_code=200, content=payload.model_dump())

    return app


__all__ = ["build_app"]
