"""Rich + JSON renderers, one module per command group.

Each renderer module exposes one ``render_*`` function per command
(e.g. ``render_doctor``). Renderers receive the command's Pydantic
payload model and write human-readable output to the shared console
via :func:`genomeclaw_toolkit._cli.console.get_console`.

Renderers never:

* Construct their own ``Console`` — they pull the shared one.
* Read TTY / colour state — that's resolved upstream in the
  ``AppContext``.
* Touch ``stdout`` directly — JSON path bypasses renderers entirely
  (handled in :func:`genomeclaw_toolkit._cli.output.emit`).

Renderers are the only place that imports from ``rich.table``,
``rich.panel``, ``rich.progress``, etc. Commands stay clean of
rendering primitives.
"""

from __future__ import annotations
