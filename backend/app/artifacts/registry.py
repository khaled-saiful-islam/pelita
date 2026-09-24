"""The kinds of artifact this app can make.

Adding slides, a one-page app or a résumé is one file implementing
`ArtifactKind` and one entry here. The tool's `kind` enum is built from this
dict, so a new kind is offered to the model by existing — there is no second
list to keep in step.
"""

from __future__ import annotations

from app.artifacts.base import ArtifactKind
from app.artifacts.games import GamesKind
from app.artifacts.model import ArtifactModel
from app.artifacts.poster import PosterKind
from app.artifacts.slides import SlidesKind
from app.artifacts.web_app import AppKind
from app.artifacts.website import WebsiteKind
from app.core.config import Settings, get_settings
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.tools.serpapi import SerpApiSearch


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
    # A poster may use a photograph somebody else took, when the design wants
    # one. Without a search key there is none to find, and it designs with
    # type, colour and drawn shape instead.
    search = (
        SerpApiSearch(api_key=settings.serpapi_key, base_url=settings.serpapi_base_url)
        if settings.search_enabled
        else None
    )
    kinds: list[ArtifactKind] = [
        PosterKind(
            model,
            refine=settings.artifact_refine_pass,
            max_bytes=settings.artifact_max_bytes,
            search=search,
        ),
        GamesKind(
            model,
            max_bytes=settings.artifact_max_bytes,
            playtest=settings.artifact_playtest,
        ),
        SlidesKind(
            model,
            # A deck is a dozen slides and their pictures, so it is allowed to
            # be several times the size of one poster.
            max_bytes=settings.artifact_max_bytes * 8,
            search=search,
        ),
        WebsiteKind(
            model,
            # Several pages and up to six photographs, embedded, because a site
            # has to keep working as one file after it is downloaded.
            max_bytes=settings.artifact_max_bytes * 4,
            search=search,
            # The same browser and the same switch as the game's playtest.
            check=settings.artifact_playtest,
        ),
        AppKind(
            model,
            max_bytes=settings.artifact_max_bytes,
            # Used in the same browser as the game's playtest, under the same
            # switch.
            check=settings.artifact_playtest,
        ),
    ]
    return {kind.name: kind for kind in kinds}
