"""Public entrypoints for skillint-py: ``lint`` and ``lint_source``."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Union

from .parse import parse_skill
from .rules import Issue, all_rules


@dataclass
class LintResult:
    """Result of a single-file lint."""

    file: str
    fatal: bool = False
    issues: List[Issue] = field(default_factory=list)


def lint_source(source: str, *, file: str = "<inline>") -> LintResult:
    """Lint an in-memory SKILL.md string."""
    if not isinstance(source, str):
        raise TypeError("skillint.lint_source: source must be a str")
    skill = parse_skill(source)
    issues = all_rules(skill, source)
    fatal = skill.parse_error is not None and skill.frontmatter is None
    return LintResult(file=file, fatal=fatal, issues=issues)


def lint(skill_md_path: Union[str, Path]) -> LintResult:
    """Lint a SKILL.md file at ``skill_md_path``.

    Spec entrypoint: ``lint(skill_md_path) -> LintResult``.
    """
    path = Path(skill_md_path)
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as err:
        return LintResult(
            file=str(path),
            fatal=True,
            issues=[
                Issue(
                    rule_id="unreadable",
                    severity="error",
                    message=f"Could not read file: {err.strerror or err}.",
                    suggestion="Check the path and permissions.",
                )
            ],
        )
    return lint_source(source, file=str(path))
