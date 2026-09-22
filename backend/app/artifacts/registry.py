"""The kinds of artifact this app can make.

Adding slides, a one-page app or a résumé is one file implementing
`ArtifactKind` and one entry here. The tool's `kind` enum is built from this
dict, so a new kind is offered to the model by existing — there is no second
list to keep in step.
"""

from __future__ import annotations

from app.artifacts.base import ArtifactKind
from app.core.config import Settings, get_settings


def build_kinds(settings: Settings | None = None) -> dict[str, ArtifactKind]:
    """Keyed by name, which is also what the model calls them."""
    settings = settings or get_settings()
    if not settings.artifacts_available:
        # No model, so the capability does not exist. The UI reads this through
        # /api/config and says nothing about artifacts rather than offering
        # something that always fails.
        return {}
    return {}
