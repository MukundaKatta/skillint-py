# skillint-py

[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**A linter for Claude Code [skill files](https://docs.claude.com/en/docs/claude-code/skills) (`SKILL.md`).** Catches malformed YAML frontmatter, missing required fields, thin descriptions, hardcoded secrets, and missing body headings before they ship.

Stdlib-only Python port of [@mukundakatta/skillint](https://github.com/MukundaKatta/skillint). No PyYAML required -- the linter only needs to recognize the simple `key: value` mapping that frontmatter actually uses.

> Note: there's a separate `claude-skill-check` package on PyPI by a different author. This package is the user's own port and uses the `-py` suffix to disambiguate.

## Install

```bash
pip install skillint-py
```

## Usage

```python
from skillint import lint

result = lint("path/to/SKILL.md")

result.fatal           # True if frontmatter could not be parsed at all
for issue in result.issues:
    print(issue.line, issue.severity, issue.rule_id, issue.message)
```

You can also lint an in-memory source string:

```python
from skillint import lint_source

source = """---
name: git-commit
description: Use when the user asks Claude to commit changes; handles co-author trailers.
---

## Triggers
"""
result = lint_source(source, file="<inline>")
```

## Result shape

```python
@dataclass
class Issue:
    rule_id: str
    severity: str           # "error" | "warning" | "info"
    message: str
    suggestion: str = ""
    line: int = 1

@dataclass
class LintResult:
    file: str
    fatal: bool
    issues: list[Issue]
```

## Rules

| Rule id | Severity | Checks |
|---|---|---|
| `missing-frontmatter` | error | File doesn't start with `---` YAML fence. |
| `yaml-parse-error` | error | Frontmatter fails to parse as a mapping. |
| `missing-required` | error | `name` or `description` is missing. |
| `empty-required` | error | `name` or `description` is empty / whitespace. |
| `kebab-case-name` | error | `name` is not kebab-case (`^[a-z][a-z0-9-]*[a-z0-9]$`). |
| `overlong-name` | warning | `name` exceeds 64 characters. |
| `short-description` | warning / error | Description below 80 chars (or below 20 -> error). |
| `no-trigger-in-description` | warning | Description lacks "when / use / trigger / handle / invoke" language. |
| `no-body-headings` | warning | Body has no `##` headings. |
| `hardcoded-secret` | error | Provider-shaped key (OpenAI, Anthropic, GitHub, AWS, Slack, Stripe, Google AI). |
| `unknown-field` | info | Frontmatter field outside the known set. |

## API differences from the JS sibling

* Stdlib-only YAML parser handles the flat `key: value` mapping that
  frontmatter actually uses. Block scalars and tagged values are not
  supported -- if your frontmatter needs them, the linter falls back to a
  `yaml-parse-error` so you'll see it loud and clear.
* No `--config` plugin loading -- this Python port runs the built-in rules.
* Spec entrypoint is `lint(skill_md_path) -> LintResult`. `lint_source` covers
  the in-memory case.

See the JS sibling's [README](https://github.com/MukundaKatta/skillint) for
the broader rationale.
