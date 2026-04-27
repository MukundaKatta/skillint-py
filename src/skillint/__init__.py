"""skillint -- lint Claude Code SKILL.md files.

Python port of @mukundakatta/skillint.

Public surface:

    from skillint import lint, lint_source, Issue, LintResult, parse_skill
"""

from .core import Issue, LintResult, lint, lint_source
from .parse import ParsedSkill, parse_skill

__version__ = "0.1.0"
VERSION = __version__

__all__ = [
    "Issue",
    "LintResult",
    "ParsedSkill",
    "VERSION",
    "lint",
    "lint_source",
    "parse_skill",
]
