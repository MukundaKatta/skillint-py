"""SKILL.md parser.

Splits the file into YAML frontmatter + body, preserving line offsets so
issue messages can point at the offending line. Frontmatter is parsed by a
tiny tolerant scanner that handles the simple ``key: value`` mapping
SKILL.md files actually use (with optional quoted strings and lists). Block
scalars and tagged values are not supported -- if your frontmatter needs
them, the linter surfaces ``yaml-parse-error``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

_FRONTMATTER_RE = re.compile(r"^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]*)$")


@dataclass
class ParsedSkill:
    """Result of :func:`parse_skill`."""

    frontmatter: Optional[dict]
    body: str
    raw_frontmatter: str = ""
    parse_error: Optional[str] = None
    frontmatter_start_line: int = 1
    body_start_line: int = 1


def parse_skill(source: str) -> ParsedSkill:
    """Split ``source`` into frontmatter + body and parse the YAML mapping."""
    match = _FRONTMATTER_RE.match(source)
    if not match:
        return ParsedSkill(frontmatter=None, body=source)
    raw_fm = match.group(1)
    body = match.group(2)
    fm_start = 2  # frontmatter starts on line 2 (line 1 is the `---` fence)
    body_start = raw_fm.count("\n") + 1 + 4  # after the closing fence
    try:
        parsed = _parse_simple_yaml(raw_fm)
    except _YamlParseError as err:
        return ParsedSkill(
            frontmatter=None,
            body=body,
            raw_frontmatter=raw_fm,
            parse_error=str(err),
            frontmatter_start_line=fm_start,
            body_start_line=body_start,
        )
    if parsed is None:
        return ParsedSkill(
            frontmatter=None,
            body=body,
            raw_frontmatter=raw_fm,
            parse_error="Frontmatter is empty.",
            frontmatter_start_line=fm_start,
            body_start_line=body_start,
        )
    if not isinstance(parsed, dict):
        return ParsedSkill(
            frontmatter=None,
            body=body,
            raw_frontmatter=raw_fm,
            parse_error="Frontmatter must be a YAML mapping (key: value pairs).",
            frontmatter_start_line=fm_start,
            body_start_line=body_start,
        )
    return ParsedSkill(
        frontmatter=parsed,
        body=body,
        raw_frontmatter=raw_fm,
        frontmatter_start_line=fm_start,
        body_start_line=body_start,
    )


def frontmatter_field_line(raw_frontmatter: str, key: str, fallback: int) -> int:
    """Return the 1-based line in ``raw_frontmatter`` where ``key:`` appears."""
    lines = raw_frontmatter.split("\n")
    for i, line in enumerate(lines):
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:", line)
        if m and m.group(1) == key:
            return fallback + i
    return fallback


# ---------------------------------------------------------------------------
# Tiny YAML mapping parser
# ---------------------------------------------------------------------------


class _YamlParseError(Exception):
    pass


_INDENT_LIST_ITEM_RE = re.compile(r"^\s*-\s")
_KEY_LINE_RE = re.compile(r"^(?P<key>[A-Za-z_][\w-]*)\s*:\s*(?P<rest>.*)$")


def _parse_simple_yaml(text: str) -> Optional[dict]:
    """Parse a flat YAML mapping with scalar/list/quoted-string values.

    Supports:
      - ``key: value`` -- string scalars (unquoted, single-quoted, double-quoted).
      - ``key: 123`` / ``key: 1.5`` / ``key: true`` / ``key: false`` / ``key: null``.
      - ``key: [a, b, c]`` -- inline lists.
      - ``key:`` followed by indented ``- item`` lines.

    Anything else raises :class:`_YamlParseError`.
    """
    text = text.strip("\r\n")
    if not text.strip():
        return None

    out: dict = {}
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        raw = lines[i]
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        m = _KEY_LINE_RE.match(raw)
        if not m:
            raise _YamlParseError(
                f"Could not parse line {i + 1}: {raw!r} (expected `key: value`)."
            )
        key = m.group("key")
        rest = m.group("rest").strip()
        if rest:
            out[key] = _parse_scalar(rest)
            i += 1
            continue
        # Empty value -- check for indented list items below.
        items: list = []
        j = i + 1
        while j < len(lines):
            nxt = lines[j]
            if not nxt.strip() or nxt.lstrip().startswith("#"):
                j += 1
                continue
            if _INDENT_LIST_ITEM_RE.match(nxt):
                value = nxt.strip()[2:].strip()
                items.append(_parse_scalar(value))
                j += 1
                continue
            break
        if items:
            out[key] = items
            i = j
        else:
            out[key] = None
            i += 1
    return out


def _parse_scalar(value: str) -> object:
    """Parse a YAML scalar -- quoted string, number, bool, null, or list."""
    s = value.strip()
    if not s:
        return ""
    # Inline list
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part) for part in _split_inline_list(inner)]
    # Quoted strings
    if (s.startswith('"') and s.endswith('"')) or (
        s.startswith("'") and s.endswith("'")
    ):
        return _unquote(s)
    low = s.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "~", ""):
        return None
    # Number
    try:
        if "." in s or "e" in low:
            return float(s)
        return int(s)
    except ValueError:
        pass
    # Strip a trailing `# comment`
    hash_at = s.find(" #")
    if hash_at != -1:
        return s[:hash_at].strip()
    return s


def _split_inline_list(inner: str) -> list[str]:
    """Split a `[a, "b, c", d]` body honoring quoted commas."""
    parts: list[str] = []
    cur: list[str] = []
    quote: Optional[str] = None
    for ch in inner:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            cur.append(ch)
            continue
        if ch == ",":
            parts.append("".join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    if cur:
        parts.append("".join(cur).strip())
    return parts


def _unquote(s: str) -> str:
    body = s[1:-1]
    if s[0] == "'":
        # YAML single-quote escapes a single quote by doubling it.
        return body.replace("''", "'")
    # Double-quoted: handle the common escapes.
    return body.encode("utf-8").decode("unicode_escape")
