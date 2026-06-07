"""Rule implementations for skillint-py."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

from .parse import ParsedSkill, frontmatter_field_line


@dataclass
class Issue:
    """One lint issue."""

    rule_id: str
    severity: str  # "error" | "warning" | "info"
    message: str
    suggestion: str = ""
    line: int = 1


REQUIRED_FIELDS = ("name", "description")
KNOWN_FIELDS = frozenset(
    {
        "name",
        "description",
        "version",
        "author",
        "license",
        "tags",
        "model",
        "allowedTools",
        "allowed-tools",
        "requiredPermissions",
        "required-permissions",
    }
)

_KEBAB_CASE_RE = re.compile(r"^[a-z][a-z0-9-]*[a-z0-9]$")
_TRIGGER_WORDS_RE = re.compile(
    r"\b(when|use|trigger|invoke|for|handle|automatically|whenever|on)\b",
    re.IGNORECASE,
)
_BODY_HEADING_RE = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)

MIN_DESCRIPTION_LENGTH = 20
SHORT_DESCRIPTION_LENGTH = 80
MAX_NAME_LENGTH = 64

# Mirrors the JS sibling's secret families. ``\b`` boundaries keep us from
# alarming on prefixes inside prose words like ``sketch``.
# Order matters: more-specific provider patterns (e.g. ``sk-ant-...``) come
# before the generic OpenAI ``sk-...`` so we don't mislabel an Anthropic key
# as OpenAI just because the looser pattern also matches it.
_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    (
        "OpenAI API key",
        re.compile(r"\bsk-(?:proj-|svcacct-|admin-|live-)?[A-Za-z0-9_-]{20,}\b"),
    ),
    ("Google AI API key", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b")),
    (
        "GitHub personal token",
        re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"),
    ),
    ("GitHub fine-grained PAT", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}\b")),
    ("Slack bot token", re.compile(r"\bxox[abp]-[0-9]+-[0-9]+-[A-Za-z0-9]+\b")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Stripe secret key", re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{20,}\b")),
]


def _to_kebab(s: str) -> str:
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", s).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"^-+|-+$", "", s)
    s = re.sub(r"--+", "-", s)
    return s


def frontmatter_rules(skill: ParsedSkill) -> List[Issue]:
    issues: List[Issue] = []

    if skill.parse_error and not skill.frontmatter:
        # No frontmatter at all -- check if it's because the file lacks the
        # `---` fence (not a parse error per se) vs broken YAML.
        if not skill.raw_frontmatter:
            issues.append(
                Issue(
                    rule_id="missing-frontmatter",
                    severity="error",
                    message="SKILL.md must begin with a YAML frontmatter block.",
                    suggestion=(
                        "Wrap metadata in `---` fences at the top of the file, e.g.\n"
                        "---\nname: my-skill\ndescription: Use when ...\n---"
                    ),
                    line=1,
                )
            )
            return issues
        issues.append(
            Issue(
                rule_id="yaml-parse-error",
                severity="error",
                message=f"YAML frontmatter parse error: {skill.parse_error}",
                suggestion="Fix the YAML syntax.",
                line=skill.frontmatter_start_line,
            )
        )
        return issues

    if not skill.frontmatter:
        issues.append(
            Issue(
                rule_id="missing-frontmatter",
                severity="error",
                message="SKILL.md must begin with a YAML frontmatter block.",
                suggestion=(
                    "Wrap metadata in `---` fences at the top of the file, e.g.\n"
                    "---\nname: my-skill\ndescription: Use when ...\n---"
                ),
                line=1,
            )
        )
        return issues

    fm = skill.frontmatter

    # Required fields
    for field in REQUIRED_FIELDS:
        if field not in fm:
            issues.append(
                Issue(
                    rule_id="missing-required",
                    severity="error",
                    message=f"Frontmatter is missing required field {field!r}.",
                    suggestion=f"Add `{field}:` to the frontmatter block.",
                    line=skill.frontmatter_start_line,
                )
            )
        else:
            value = fm[field]
            if not isinstance(value, str) or not value.strip():
                issues.append(
                    Issue(
                        rule_id="empty-required",
                        severity="error",
                        message=(
                            f"Frontmatter field {field!r} must be a non-empty string."
                        ),
                        suggestion=f"Provide a value for {field!r}.",
                        line=frontmatter_field_line(
                            skill.raw_frontmatter, field, skill.frontmatter_start_line
                        ),
                    )
                )

    # name: kebab-case + length
    name_val = fm.get("name")
    if isinstance(name_val, str) and name_val.strip():
        name_line = frontmatter_field_line(
            skill.raw_frontmatter, "name", skill.frontmatter_start_line
        )
        if not _KEBAB_CASE_RE.match(name_val):
            issues.append(
                Issue(
                    rule_id="kebab-case-name",
                    severity="error",
                    message=(
                        f"`name` must be kebab-case (lowercase, digits, hyphens), got "
                        f"{name_val!r}."
                    ),
                    suggestion=f"Rename to {_to_kebab(name_val)!r}.",
                    line=name_line,
                )
            )
        if len(name_val) > MAX_NAME_LENGTH:
            issues.append(
                Issue(
                    rule_id="overlong-name",
                    severity="warning",
                    message=(
                        f"`name` is {len(name_val)} chars; the skill name surfaces in UI "
                        "and should be concise."
                    ),
                    suggestion=f"Shorten to <= {MAX_NAME_LENGTH} chars.",
                    line=name_line,
                )
            )

    # description: length + trigger language
    desc_val = fm.get("description")
    if isinstance(desc_val, str):
        trimmed = desc_val.strip()
        desc_line = frontmatter_field_line(
            skill.raw_frontmatter, "description", skill.frontmatter_start_line
        )
        if 0 < len(trimmed) < MIN_DESCRIPTION_LENGTH:
            issues.append(
                Issue(
                    rule_id="short-description",
                    severity="error",
                    message=(
                        f"`description` is too short ({len(trimmed)} chars). Claude uses this "
                        "to decide when to invoke the skill."
                    ),
                    suggestion=(
                        'Aim for >= 100 chars describing purpose and triggers ("Use when ...").'
                    ),
                    line=desc_line,
                )
            )
        elif MIN_DESCRIPTION_LENGTH <= len(trimmed) < SHORT_DESCRIPTION_LENGTH:
            issues.append(
                Issue(
                    rule_id="short-description",
                    severity="warning",
                    message=(
                        f"`description` is short ({len(trimmed)} chars). Consider adding "
                        "trigger keywords."
                    ),
                    suggestion='Extend with "Use when ..." so Claude can match user intent.',
                    line=desc_line,
                )
            )
        if len(trimmed) >= MIN_DESCRIPTION_LENGTH and not _TRIGGER_WORDS_RE.search(
            trimmed
        ):
            issues.append(
                Issue(
                    rule_id="no-trigger-in-description",
                    severity="warning",
                    message="`description` doesn't tell Claude *when* to use the skill.",
                    suggestion=(
                        'Start with "Use when ..." or include trigger keywords '
                        '("trigger on ...", "handle ...", "invoke for ...").'
                    ),
                    line=desc_line,
                )
            )

    # Unknown fields
    for k in fm:
        if k not in KNOWN_FIELDS:
            issues.append(
                Issue(
                    rule_id="unknown-field",
                    severity="info",
                    message=f"Unknown frontmatter field {k!r}.",
                    suggestion=f"Known fields: {', '.join(sorted(KNOWN_FIELDS))}.",
                    line=frontmatter_field_line(
                        skill.raw_frontmatter, k, skill.frontmatter_start_line
                    ),
                )
            )

    return issues


def body_rule(skill: ParsedSkill) -> List[Issue]:
    body = skill.body
    if not body.strip():
        return [
            Issue(
                rule_id="no-body-headings",
                severity="warning",
                message="Skill body is empty.",
                suggestion=(
                    "Add instructions for Claude under the frontmatter. At least one "
                    "## heading is expected."
                ),
                line=skill.body_start_line,
            )
        ]
    if not _BODY_HEADING_RE.search(body):
        return [
            Issue(
                rule_id="no-body-headings",
                severity="warning",
                message="Skill body has no headings. Structure instructions with `##` sections.",
                suggestion=(
                    "Add at least one section like `## Triggers` or `## Steps`."
                ),
                line=skill.body_start_line,
            )
        ]
    return []


def _overlaps(span: tuple[int, int], claimed: list[tuple[int, int]]) -> bool:
    start, end = span
    for c_start, c_end in claimed:
        if start < c_end and c_start < end:
            return True
    return False


def secrets_rule(skill: ParsedSkill, source: str) -> List[Issue]:
    issues: List[Issue] = []
    lines = source.split("\n")
    # Track spans already claimed by a more-specific (earlier) pattern, keyed by
    # line index. The generic OpenAI ``sk-...`` pattern also matches Anthropic
    # ``sk-ant-...`` keys; without this, the same secret would be reported twice
    # with conflicting labels. Patterns are ordered most-specific first, so the
    # first match for a span wins.
    claimed: dict[int, list[tuple[int, int]]] = {}
    for label, pattern in _SECRET_PATTERNS:
        for i, line in enumerate(lines):
            matched = False
            for m in pattern.finditer(line):
                span = m.span()
                if _overlaps(span, claimed.get(i, [])):
                    continue
                claimed.setdefault(i, []).append(span)
                value = m.group(0)
                masked = value[:10] + "..." + value[-4:]
                issues.append(
                    Issue(
                        rule_id="hardcoded-secret",
                        severity="error",
                        message=(
                            f"Possible hardcoded {label} ({masked}) in SKILL.md. "
                            "Anthropic skills are distributed; never commit secrets."
                        ),
                        suggestion="Reference the env var or a runtime secret store instead.",
                        line=i + 1,
                    )
                )
                matched = True
                break  # one hit per pattern is enough; avoid alarm spam
            if matched:
                break
    return issues


def all_rules(skill: ParsedSkill, source: str) -> List[Issue]:
    issues: List[Issue] = []
    issues.extend(frontmatter_rules(skill))
    if skill.frontmatter:
        issues.extend(body_rule(skill))
    issues.extend(secrets_rule(skill, source))
    issues.sort(key=lambda i: (i.line, i.rule_id))
    return issues
