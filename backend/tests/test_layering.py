"""The layering rule, enforced rather than documented.

`services/`, `providers/`, `guards/`, `context/` and `tools/` hold logic. `api/`
holds HTTP. If logic starts importing FastAPI it stops being testable without a
request and stops being reusable outside one, and that happens gradually enough
that nobody notices. So it fails a test instead.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "app"
LOGIC_PACKAGES = ("services", "providers", "guards", "context", "tools", "core")
FORBIDDEN_ROOTS = {"fastapi", "starlette"}


def logic_modules() -> list[Path]:
    return sorted(
        path
        for package in LOGIC_PACKAGES
        for path in (APP / package).rglob("*.py")
        if path.name != "__init__.py"
    )


def imported_roots(source: str) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


@pytest.mark.parametrize("module", logic_modules(), ids=lambda p: str(p.relative_to(APP)))
def test_logic_layer_does_not_import_http_framework(module: Path) -> None:
    offenders = imported_roots(module.read_text()) & FORBIDDEN_ROOTS
    assert not offenders, (
        f"{module.relative_to(APP)} imports {', '.join(sorted(offenders))}. "
        "Move the HTTP concern into app/api/ and keep this layer framework-free."
    )


def test_logic_packages_are_not_empty() -> None:
    """Guards the guard: an empty parametrize would make the rule vacuously pass."""
    assert len(logic_modules()) >= 5
