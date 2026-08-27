"""Unit tests for the dynamic eligibility-rule engine (services.eligibility)."""

import pytest

from services.eligibility import CATALOG, catalog, check_eligibility


class _Contest:
    """Minimal stand-in with the attributes the checkers read."""
    def __init__(self, rules, start_date=None):
        self.eligibility_rules = rules
        self.start_date = start_date


def _meta(**over):
    m = {
        "namespace": 0, "byte_count": 1234, "word_count": 500,
        "ref_new_count": 3, "ref_reused_count": 1, "image_count": 2,
        "creator": "Alice", "created_at": "2020-01-01T00:00:00Z",
    }
    m.update(over)
    return m


# --- catalog --------------------------------------------------------------- #
def test_catalog_shape():
    keys = {r["key"] for r in catalog()}
    assert {"min_byte_count", "min_word_count", "min_reference_count",
            "min_image_count", "allowed_submission_type", "author_only"} <= keys
    for r in CATALOG:
        assert r["type"] in ("number", "enum", "boolean")
        if r["type"] == "enum":
            assert r["options"]


# --- namespace (always enforced) ------------------------------------------- #
def test_non_mainspace_always_rejected_even_with_no_rules():
    with pytest.raises(ValueError, match="main-namespace"):
        check_eligibility(_Contest({}), _meta(namespace=1))


# --- number rules ---------------------------------------------------------- #
def test_min_bytes():
    check_eligibility(_Contest({"min_byte_count": 1000}), _meta())  # 1234 ok
    with pytest.raises(ValueError, match="at least 5000 bytes"):
        check_eligibility(_Contest({"min_byte_count": 5000}), _meta())


def test_min_images():
    check_eligibility(_Contest({"min_image_count": 2}), _meta())  # exactly 2 ok
    with pytest.raises(ValueError, match="at least 5 images"):
        check_eligibility(_Contest({"min_image_count": 5}), _meta())


def test_min_words_and_hard_fail_when_unavailable():
    with pytest.raises(ValueError, match="at least 1000 words"):
        check_eligibility(_Contest({"min_word_count": 1000}), _meta())
    with pytest.raises(ValueError, match="[Cc]ould not determine.*word"):
        check_eligibility(_Contest({"min_word_count": 100}), _meta(word_count=None))


def test_min_refs_total_and_hard_fail():
    with pytest.raises(ValueError, match="at least 10 references"):
        check_eligibility(_Contest({"min_reference_count": 10}), _meta())
    with pytest.raises(ValueError, match="[Cc]ould not determine.*reference"):
        check_eligibility(_Contest({"min_reference_count": 5}), _meta(ref_new_count=None))


# --- author_only (boolean, needs the submitter) ---------------------------- #
def test_author_only_allows_creator():
    check_eligibility(_Contest({"author_only": True}), _meta(creator="Alice"),
                      submitter="Alice")


def test_author_only_rejects_non_creator():
    with pytest.raises(ValueError, match="creator may submit"):
        check_eligibility(_Contest({"author_only": True}), _meta(creator="Alice"),
                          submitter="Bob")


def test_author_only_false_is_noop():
    check_eligibility(_Contest({"author_only": False}), _meta(creator="Alice"),
                      submitter="Bob")


# --- unknown keys are ignored (forward-compatible) ------------------------- #
def test_unknown_rule_key_is_ignored():
    check_eligibility(_Contest({"totally_made_up_rule": 5}), _meta())
