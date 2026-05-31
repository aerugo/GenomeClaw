"""Host-side personal-context profile storage.

The profile is the single most identifying host-side dataset after the
raw genome itself. It lives as a JSON document at
``<derived_root>/host_profile.json`` with an append-only audit log
beside it. This package owns the on-disk lifecycle (atomic read/write,
audit, completeness); the typed shape lives in
:mod:`genomeclaw_toolkit.schemas.host_profile`.
"""

from __future__ import annotations
