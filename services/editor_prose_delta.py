#!/usr/bin/env python3
"""editor_prose_delta.py — per-revision / per-user "editor-words added".

Builds on editor_prose_counter to answer the campaign scoring question: **who
added how many authored prose words** to an article over a period. Because it
uses the wikitext editor-prose counter (no HTML rendering) and fetches wikitext
in batches of 50 revisions, a whole edit-a-thon article is scored in a handful
of API calls — history metadata (paginated) + a few batched wikitext fetches.

For each in-scope revision the authored-word delta is
    editor_prose_words(revision) - editor_prose_words(parent)
attributed to the revision's author, then summed per user. A revision whose
wikitext can't be fetched (suppressed) is flagged unmeasurable, never counted 0.

Entry point: analyze(article_link, start, end, user) -> report dict.
"""

from dataclasses import asdict, dataclass

import requests

from services.editor_prose_counter import (
    HTTP_TIMEOUT, USER_AGENT, count_references, editor_prose_words,
    fetch_namespace_names, fetch_wikitext_batch, title_from_link)


# --------------------------------------------------------------------------- #
# History (metadata only — cheap, paginated)
# --------------------------------------------------------------------------- #
def fetch_revision_history(base_url, title, start=None, end=None, user=None):
    """Revisions oldest→newest: {revid, parentid, user, timestamp}.

    When a period is given, only that window is fetched (rvstart/rvend) so an
    ancient article isn't paginated in full. When `user` is given, the API
    filters to that user's revisions server-side (rvuser) — far fewer rows to
    paginate on a busy article. Either way each returned revision still carries
    its parentid, whose wikitext is fetched separately for the delta baseline
    (so per-user deltas remain correct even when the parent is another editor's).
    """
    api = f"{base_url}/w/api.php"
    params = {
        "action": "query", "format": "json", "formatversion": "2",
        "prop": "revisions", "titles": title,
        "rvprop": "ids|timestamp|user|flags", "rvlimit": "max",
        "rvdir": "newer", "redirects": "1",
    }
    if start:
        params["rvstart"] = start if "T" in start else start + "T00:00:00Z"
    if end:
        params["rvend"] = end if "T" in end else end + "T23:59:59Z"
    if user:
        params["rvuser"] = user  # fetch only this contributor's revisions

    revisions = []
    cont = {}
    while True:
        data = requests.get(api, params={**params, **cont},
                            headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT).json()
        pages = data.get("query", {}).get("pages", [])
        if not pages or pages[0].get("missing"):
            raise ValueError(f"Article not found: {title}")
        revisions.extend(pages[0].get("revisions", []))
        if "continue" in data:
            cont = data["continue"]
        else:
            break
    return revisions


# --------------------------------------------------------------------------- #
# Pure logic (unit-tested offline)
# --------------------------------------------------------------------------- #
def select_scope(revs, start=None, end=None, user=None):
    """Revisions within [start, end] (inclusive; bare end = end of day) and/or
    by `user`. ISO timestamps sort lexicographically, so string compare works."""
    end_bound = (end + "T23:59:59Z") if (end and len(end) == 10) else end
    out = []
    for r in revs:
        ts = r.get("timestamp", "")
        if start and ts < start:
            continue
        if end_bound and ts > end_bound:
            continue
        if user and r.get("user") != user:
            continue
        out.append(r)
    return out


def revids_to_measure(scoped):
    """Revids to fetch wikitext for: each scoped revision + its parent (the
    parent gives the pre-edit word count for the delta)."""
    need = set()
    for r in scoped:
        need.add(r["revid"])
        if r.get("parentid"):
            need.add(r["parentid"])
    return need


@dataclass
class UserContribution:
    user: str
    edits: int = 0
    words_added: int = 0     # sum of positive deltas (gross authored words added)
    words_removed: int = 0   # abs sum of negative deltas
    words_net: int = 0       # signed sum — net authored contribution
    refs_added: int = 0      # <ref> citations added (gross)
    refs_removed: int = 0    # <ref> citations removed (abs)
    refs_net: int = 0        # signed sum — net references
    unmeasured_edits: int = 0
    first_edit: str = ""
    last_edit: str = ""


def aggregate_deltas(scoped, words_by_id, refs_by_id=None):
    """Pure: per-revision word & reference deltas + per-user totals.

    Returns (per_revision, users_sorted, warnings). A revid absent from
    words_by_id (unfetchable/suppressed) makes its deltas unmeasurable (None),
    counted as an unmeasured edit rather than a fabricated 0. `refs_by_id` shares
    the same revids as `words_by_id` (both come from the same wikitext fetch).
    """
    refs_by_id = refs_by_id or {}
    warned = set()

    def wc(revid):  # words — an absent revid is unmeasurable and warned
        if not revid:
            return 0  # page creation: no parent
        w = words_by_id.get(revid)
        if w is None:
            warned.add(revid)
            return None
        return w

    def rc(revid):  # refs — a secondary metric; absent => None but no warning
        if not revid:
            return 0
        return refs_by_id.get(revid)

    users = {}
    per_revision = []
    for r in scoped:
        user = r.get("user", "(unknown)")
        parent = r.get("parentid")
        ts = r.get("timestamp", "")
        w_rev, w_par = wc(r["revid"]), wc(parent)
        r_rev, r_par = rc(r["revid"]), rc(parent)
        word_delta = None if (w_rev is None or w_par is None) else (w_rev - w_par)
        ref_delta = None if (r_rev is None or r_par is None) else (r_rev - r_par)

        stats = users.setdefault(user, UserContribution(user=user))
        stats.edits += 1
        if word_delta is None:
            stats.unmeasured_edits += 1
        else:
            stats.words_net += word_delta
            if word_delta > 0:
                stats.words_added += word_delta
            else:
                stats.words_removed += -word_delta
        if ref_delta is not None:
            stats.refs_net += ref_delta
            if ref_delta > 0:
                stats.refs_added += ref_delta
            else:
                stats.refs_removed += -ref_delta
        if not stats.first_edit or ts < stats.first_edit:
            stats.first_edit = ts
        if ts > stats.last_edit:
            stats.last_edit = ts
        per_revision.append({"revid": r["revid"], "user": user, "timestamp": ts,
                             "words_delta": word_delta, "refs_delta": ref_delta})

    warnings = [f"could not fetch wikitext for rev {rid} — delta unmeasurable"
                for rid in sorted(warned)]
    users_sorted = sorted(users.values(), key=lambda s: s.words_added, reverse=True)
    return per_revision, users_sorted, warnings


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def analyze(article_link, start=None, end=None, user=None,
            category_names=None, file_names=None):
    base_url, title = title_from_link(article_link)
    # Push the user filter to the API (rvuser) so a busy article isn't paginated
    # in full; select_scope still applies the exact period bounds as a backstop.
    revs = fetch_revision_history(base_url, title, start=start, end=end, user=user)
    scoped = select_scope(revs, start, end, user)
    if category_names is None or file_names is None:
        category_names, file_names = fetch_namespace_names(base_url)

    contents = fetch_wikitext_batch(base_url, sorted(revids_to_measure(scoped)))
    # Word and reference counts come from the SAME wikitext (no extra fetches).
    words_by_id = {rid: editor_prose_words(wt, category_names, file_names)
                   for rid, wt in contents.items()}
    refs_by_id = {rid: count_references(wt) for rid, wt in contents.items()}
    per_revision, users, warnings = aggregate_deltas(scoped, words_by_id, refs_by_id)

    return {
        "base_url": base_url, "title": title,
        "period_start": start, "period_end": end, "user_filter": user,
        "revisions_fetched": len(revs), "revisions_in_scope": len(scoped),
        "wikitext_fetches": len(contents),
        "words_added_total": sum(u.words_added for u in users),
        "refs_added_total": sum(u.refs_added for u in users),
        "per_revision": per_revision,
        "users": [asdict(u) for u in users],
        "warnings": warnings,
    }
