"""Article-submission eligibility rules — the dynamic, typed validation system.

Eligibility rules decide whether an article may be *submitted* to a contest
(enforced at /evaluate). They are separate from scoring rules. A contest stores
its chosen rules as a JSON dict `{rule_key: value}` (Contest.eligibility_rules);
this module is the single source of truth for:

  - CATALOG      — the rules a contest creator can add, each with a `type`
                   (number | enum | boolean) the UI uses to render its input.
  - CHECKERS     — one validator per rule key; check_eligibility() runs the
                   checkers for whatever rules the contest has set.

Adding a new rule = one CATALOG entry + one checker. Nothing else changes.

Note: "main-namespace (article) pages only" is always enforced (not a catalog
rule) — every contest rejects Talk:/User:/Category:/… regardless of rules.
"""

from datetime import datetime, timezone


# --------------------------------------------------------------------------- #
# Catalog — what a creator can add. `type` drives the form input:
#   number  -> a numeric value input (unit/placeholder shown)
#   enum    -> a single choice from `options`
#   boolean -> an on/off toggle (present == enabled)
# --------------------------------------------------------------------------- #
CATALOG = [
    {
        "key": "min_byte_count",
        "label": "Minimum byte count",
        "type": "number",
        "unit": "bytes",
        "default": 0,
        "description": "Article size must be at least this many bytes.",
    },
    {
        "key": "min_word_count",
        "label": "Minimum word count",
        "type": "number",
        "unit": "words",
        "default": 0,
        "description": "Editor-authored prose must be at least this many words.",
    },
    {
        "key": "min_reference_count",
        "label": "Minimum reference count",
        "type": "number",
        "unit": "references",
        "default": 0,
        "description": "Article must have at least this many references.",
    },
    {
        "key": "min_image_count",
        "label": "Minimum image count",
        "type": "number",
        "unit": "images",
        "default": 0,
        "description": "Article must embed at least this many images.",
    },
    {
        "key": "allowed_submission_type",
        "label": "Allowed submission type",
        "type": "enum",
        "default": "both",
        "options": [
            {"value": "new", "label": "New articles only"},
            {"value": "expansion", "label": "Expansions only"},
            {"value": "both", "label": "Both (new + expansions)"},
        ],
        "description": "Restrict by whether the article was created during the contest.",
    },
    {
        "key": "author_only",
        "label": "Submit by author only",
        "type": "boolean",
        "default": True,
        "description": "Only the article's creator may submit it.",
    },
]

_CATALOG_BY_KEY = {r["key"]: r for r in CATALOG}


def catalog():
    """The rule catalog, for the API / form (data-driven UI)."""
    return CATALOG


def is_rule(key):
    return key in _CATALOG_BY_KEY


# --------------------------------------------------------------------------- #
# Checkers — one per rule key. Each raises ValueError(message) on failure.
# Signature: checker(value, metadata, ctx) where ctx = {contest, submitter}.
# --------------------------------------------------------------------------- #
def _as_utc(dt):
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _created_instant(timestamp):
    if not timestamp:
        return None
    try:
        return _as_utc(datetime.fromisoformat(timestamp.replace("Z", "+00:00")))
    except ValueError:
        return None


def _check_min_bytes(value, metadata, ctx):
    if value and (metadata.get("byte_count") or 0) < value:
        raise ValueError(f"Article must be at least {value} bytes")


def _check_min_words(value, metadata, ctx):
    if not value:
        return
    words = metadata.get("word_count")
    if words is None:
        raise ValueError("Could not determine the article's word count; please try again")
    if words < value:
        raise ValueError(f"Article must have at least {value} words")


def _check_min_refs(value, metadata, ctx):
    if not value:
        return
    if metadata.get("ref_new_count") is None:
        raise ValueError("Could not determine the article's reference count; please try again")
    total = (metadata.get("ref_new_count") or 0) + (metadata.get("ref_reused_count") or 0)
    if total < value:
        raise ValueError(f"Article must have at least {value} references")


def _check_min_images(value, metadata, ctx):
    if value and (metadata.get("image_count") or 0) < value:
        raise ValueError(f"Article must have at least {value} images")


def _check_submission_type(value, metadata, ctx):
    if value not in ("new", "expansion"):
        return  # "both" (or unset) imposes no restriction
    start = _as_utc(ctx["contest"].start_date)
    created = _created_instant(metadata.get("created_at"))
    if not start or created is None:
        return
    if value == "new" and created < start:
        raise ValueError(
            "This contest only accepts newly created articles; this article was "
            "created before the contest start date")
    if value == "expansion" and created >= start:
        raise ValueError(
            "This contest only accepts expansions of existing articles; this "
            "article was created on or after the contest start date")


def _check_author_only(value, metadata, ctx):
    if not value:
        return
    creator = metadata.get("creator")
    submitter = ctx.get("submitter")
    if creator and submitter and creator != submitter:
        raise ValueError("Only the article's creator may submit it to this contest")


CHECKERS = {
    "min_byte_count": _check_min_bytes,
    "min_word_count": _check_min_words,
    "min_reference_count": _check_min_refs,
    "min_image_count": _check_min_images,
    "allowed_submission_type": _check_submission_type,
    "author_only": _check_author_only,
}


def check_eligibility(contest, metadata, submitter=None):
    """Run every eligibility rule the contest has set. Raises ValueError on the
    first failure. Main-namespace-only is always enforced first."""
    if metadata.get("namespace") != 0:
        raise ValueError("Only main-namespace (article) pages can be submitted")

    ctx = {"contest": contest, "submitter": submitter}
    for key, value in (contest.eligibility_rules or {}).items():
        checker = CHECKERS.get(key)
        if checker is not None:
            checker(value, metadata, ctx)
