"""Guard protocol and the values that cross it.

A guard inspects text on its way into the prompt and reports what it found. It
does not decide policy — whether a finding blocks, sanitises or merely warns is
the caller's business, which is what lets the same guard run over user input and
over text fetched from the internet with different consequences.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Protocol, runtime_checkable


class ContentSource(StrEnum):
    """Where the text came from.

    The distinction matters more than it looks. A user telling the assistant to
    ignore its instructions is their prerogative — it is their assistant. A web
    page telling it the same thing is an attack, because nobody asked that page
    for instructions.
    """

    USER_INPUT = "user_input"
    WEB_SEARCH = "web_search"
    NEWS = "news"
    DOCUMENT = "document"


class Severity(IntEnum):
    NONE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3

    @property
    def label(self) -> str:
        return self.name.lower()


@dataclass(frozen=True, slots=True)
class Finding:
    rule: str
    severity: Severity
    # The matched text, truncated. Shown in the banner so a person can judge the
    # finding rather than take the guard's word for it.
    evidence: str


@dataclass(frozen=True, slots=True)
class GuardVerdict:
    flagged: bool
    severity: Severity
    findings: tuple[Finding, ...]
    # Text with anything neutralised. Equal to the input when nothing fired.
    sanitized: str
    source: ContentSource

    @classmethod
    def clean(cls, text: str, source: ContentSource) -> GuardVerdict:
        return cls(
            flagged=False,
            severity=Severity.NONE,
            findings=(),
            sanitized=text,
            source=source,
        )

    @property
    def rules(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(f.rule for f in self.findings))

    def as_event(self) -> dict[str, object]:
        return {
            "source": str(self.source),
            "severity": self.severity.label,
            "rules": list(self.rules),
            "findings": [
                {"rule": f.rule, "severity": f.severity.label, "evidence": f.evidence}
                for f in self.findings
            ],
        }


@runtime_checkable
class Guard(Protocol):
    """Adding a guard is one file implementing this plus one registry line."""

    name: str

    def inspect(self, text: str, source: ContentSource) -> GuardVerdict: ...
