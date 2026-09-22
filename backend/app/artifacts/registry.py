"""The kinds of artifact this app can make.

Adding slides, a one-page app or a résumé is one file implementing
`ArtifactKind` and one entry here. The tool's `kind` enum is built from this
dict, so a new kind is offered to the model by existing — there is no second
list to keep in step.
"""

from __future__ import annotations

from app.artifacts.base import ArtifactKind
from app.artifacts.model import ArtifactModel
from app.artifacts.poster import PosterKind
from app.core.config import Settings, get_settings
from app.providers.openai_compatible import OpenAICompatibleProvider


def build_kinds(settings: Settings | None = None) -> dict[str, ArtifactKind]:
    """Keyed by name, which is also what the model calls them."""
    settings = settings or get_settings()
    if not settings.artifacts_available:
        # No model, so the capability does not exist. The UI reads this through
        # /api/config and says nothing about artifacts rather than offering
        # something that always fails.
        return {}

    model = ArtifactModel(
        OpenAICompatibleProvider(
            base_url=settings.resolved_artifact_base_url,
            api_key=settings.resolved_artifact_api_key,
            model=settings.artifact_model,
            timeout=settings.artifact_timeout_seconds,
        ),
        max_tokens=settings.artifact_max_tokens,
    )
    kinds: list[ArtifactKind] = [PosterKind(model, refine=settings.artifact_refine_pass)]
    return {kind.name: kind for kind in kinds}
