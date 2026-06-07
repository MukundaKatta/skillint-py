"""Tests for skillint.lint and lint_source."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from skillint import LintResult, lint, lint_source, parse_skill


def _ids(result: LintResult) -> set[str]:
    return {i.rule_id for i in result.issues}


def _good_skill(description: str | None = None) -> str:
    desc = description or (
        "Use when the user asks Claude to commit changes; handles "
        "co-author trailers and conventional-commit prefixes."
    )
    return textwrap.dedent(f"""\
        ---
        name: git-commit
        description: {desc}
        ---

        ## Triggers
        - User says "commit"
    """)


# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------


def test_clean_skill_returns_no_issues():
    r = lint_source(_good_skill())
    assert r.fatal is False
    assert r.issues == []


def test_missing_frontmatter_flagged():
    r = lint_source("# Just a heading, no fences\n\nbody")
    ids = _ids(r)
    assert "missing-frontmatter" in ids


def test_missing_required_field_flagged():
    src = textwrap.dedent("""\
        ---
        name: just-a-name
        ---

        ## Section
    """)
    r = lint_source(src)
    msgs = [i.message for i in r.issues if i.rule_id == "missing-required"]
    assert any("'description'" in m for m in msgs)


def test_kebab_case_name_required():
    src = textwrap.dedent("""\
        ---
        name: NotKebabCase
        description: Use when the user does X. Long enough description for the linter to be happy.
        ---

        ## Triggers
    """)
    r = lint_source(src)
    assert "kebab-case-name" in _ids(r)


def test_overlong_name_warning():
    long_name = "a" + ("-very-long-skill-name" * 4)  # > 64 chars
    src = textwrap.dedent(f"""\
        ---
        name: {long_name}
        description: Use when the user does X. Long enough description for the linter to be happy.
        ---

        ## Triggers
    """)
    r = lint_source(src)
    assert "overlong-name" in _ids(r)


def test_short_description_error_below_20_chars():
    src = textwrap.dedent("""\
        ---
        name: short
        description: too short
        ---

        ## Triggers
    """)
    r = lint_source(src)
    issue = next(i for i in r.issues if i.rule_id == "short-description")
    assert issue.severity == "error"


def test_short_description_warning_between_20_and_80():
    src = textwrap.dedent("""\
        ---
        name: medium
        description: Use when the user asks for X.
        ---

        ## Triggers
    """)
    r = lint_source(src)
    short = [i for i in r.issues if i.rule_id == "short-description"]
    assert short and short[0].severity == "warning"


def test_no_trigger_in_description_warning():
    src = textwrap.dedent("""\
        ---
        name: notrigger
        description: This skill exists. It does its job. It is well-tested. It is reliable.
        ---

        ## Triggers
    """)
    r = lint_source(src)
    assert "no-trigger-in-description" in _ids(r)


def test_unknown_field_info_severity():
    src = textwrap.dedent("""\
        ---
        name: unknown-field
        description: Use when the user does X. Long enough description for the linter to be happy.
        weirdField: yes
        ---

        ## Triggers
    """)
    r = lint_source(src)
    issue = next(i for i in r.issues if i.rule_id == "unknown-field")
    assert issue.severity == "info"


# ---------------------------------------------------------------------------
# Body
# ---------------------------------------------------------------------------


def test_no_body_headings_flagged():
    src = textwrap.dedent("""\
        ---
        name: noheadings
        description: Use when the user does X. Long enough description for the linter to be happy.
        ---

        Just some prose without any markdown headings.
    """)
    r = lint_source(src)
    assert "no-body-headings" in _ids(r)


def test_empty_body_flagged():
    src = textwrap.dedent("""\
        ---
        name: empty-body
        description: Use when the user does X. Long enough description for the linter to be happy.
        ---

    """)
    r = lint_source(src)
    issue = next(i for i in r.issues if i.rule_id == "no-body-headings")
    assert "empty" in issue.message.lower()


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------


def test_anthropic_secret_in_body_flagged():
    src = textwrap.dedent("""\
        ---
        name: leaky
        description: Use when the user does X. Long enough description for the linter to be happy.
        ---

        ## Triggers

        Use this token: sk-ant-1234567890abcdef1234567890abcdef
    """)
    r = lint_source(src)
    issue = next(i for i in r.issues if i.rule_id == "hardcoded-secret")
    assert "Anthropic" in issue.message
    # Masked version should appear in the message.
    assert "..." in issue.message


def test_aws_secret_flagged():
    src = textwrap.dedent("""\
        ---
        name: aws-leak
        description: Use when the user does X. Long enough description for the linter to be happy.
        ---

        ## Setup

        Set AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE in your env.
    """)
    r = lint_source(src)
    msgs = [i.message for i in r.issues if i.rule_id == "hardcoded-secret"]
    assert any("AWS" in m for m in msgs)


def test_anthropic_key_not_double_flagged_as_openai():
    # The generic OpenAI `sk-...` pattern also matches Anthropic `sk-ant-...`
    # keys. A single key must be reported once, with the most-specific label.
    src = textwrap.dedent("""\
        ---
        name: leaky
        description: Use when the user does X. Long enough description for the linter to be happy.
        ---

        ## Triggers

        Use this token: sk-ant-1234567890abcdef1234567890abcdef
    """)
    r = lint_source(src)
    secret_msgs = [i.message for i in r.issues if i.rule_id == "hardcoded-secret"]
    assert len(secret_msgs) == 1
    assert "Anthropic" in secret_msgs[0]
    assert "OpenAI" not in secret_msgs[0]


def test_genuine_openai_key_still_flagged():
    src = textwrap.dedent("""\
        ---
        name: openai-leak
        description: Use when the user does X. Long enough description for the linter to be happy.
        ---

        ## Setup

        key: sk-proj-abcdef1234567890ABCDEF1234
    """)
    r = lint_source(src)
    msgs = [i.message for i in r.issues if i.rule_id == "hardcoded-secret"]
    assert any("OpenAI" in m for m in msgs)


def test_no_false_positive_on_prose():
    src = textwrap.dedent("""\
        ---
        name: clean
        description: Use when the user asks for X; handles all the relevant cases gracefully.
        ---

        ## Triggers

        Mentioning sk- or AKIA in prose without a key body shouldn't trigger.
    """)
    r = lint_source(src)
    assert "hardcoded-secret" not in _ids(r)


# ---------------------------------------------------------------------------
# Filesystem
# ---------------------------------------------------------------------------


def test_lint_reads_file_from_disk(tmp_path: Path):
    f = tmp_path / "SKILL.md"
    f.write_text(_good_skill())
    r = lint(f)
    assert r.fatal is False
    assert r.file == str(f)
    assert r.issues == []


def test_lint_missing_file_marked_fatal(tmp_path: Path):
    r = lint(tmp_path / "missing.md")
    assert r.fatal is True
    assert r.issues[0].rule_id == "unreadable"


def test_lint_source_rejects_non_string():
    with pytest.raises(TypeError):
        lint_source(123)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Parser unit-level
# ---------------------------------------------------------------------------


def test_parse_skill_extracts_frontmatter_and_body():
    src = _good_skill()
    s = parse_skill(src)
    assert s.frontmatter is not None
    assert s.frontmatter["name"] == "git-commit"
    assert "Triggers" in s.body


def test_parse_skill_handles_quoted_strings():
    src = textwrap.dedent("""\
        ---
        name: "quoted-name"
        description: 'Use when X happens; this string is long enough to satisfy the linter.'
        ---

        ## H
    """)
    s = parse_skill(src)
    assert s.frontmatter["name"] == "quoted-name"
    assert "Use when X" in s.frontmatter["description"]


def test_parse_skill_returns_parse_error_for_bad_yaml():
    src = textwrap.dedent("""\
        ---
        : not a key
        ---

        body
    """)
    s = parse_skill(src)
    assert s.frontmatter is None
    assert s.parse_error
