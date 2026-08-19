"""Offline unit tests for the editor-prose delta / per-user aggregation."""

import pytest

from services import editor_prose_delta as epd


def _rev(revid, parentid, user, ts):
    return {"revid": revid, "parentid": parentid, "user": user, "timestamp": ts}


# --- fetch_revision_history: server-side user filter + robust errors --------- #
class _FakeResp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def _mock_get(monkeypatch, response, captured):
    def fake_get(url, params=None, headers=None, timeout=None):
        captured.clear()
        captured.update(params or {})
        return _FakeResp(response)
    monkeypatch.setattr(epd.requests, "get", fake_get)


def test_history_passes_rvuser_when_user_given(monkeypatch):
    captured = {}
    _mock_get(monkeypatch, {"query": {"pages": [{"revisions": []}]}}, captured)
    epd.fetch_revision_history("https://en.wikipedia.org", "Cat", user="Alice")
    assert captured.get("rvuser") == "Alice"


def test_history_omits_rvuser_without_user(monkeypatch):
    captured = {}
    _mock_get(monkeypatch, {"query": {"pages": [{"revisions": []}]}}, captured)
    epd.fetch_revision_history("https://en.wikipedia.org", "Cat")
    assert "rvuser" not in captured


def test_history_missing_page_raises_valueerror_not_systemexit(monkeypatch):
    _mock_get(monkeypatch, {"query": {"pages": [{"missing": True}]}}, {})
    with pytest.raises(ValueError):
        epd.fetch_revision_history("https://en.wikipedia.org", "NoSuchArticle")


# --- select_scope ----------------------------------------------------------- #
def test_select_scope_period_and_user():
    revs = [
        _rev(1, 0, "A", "2026-07-01T00:00:00Z"),
        _rev(2, 1, "A", "2026-08-05T10:00:00Z"),
        _rev(3, 2, "B", "2026-08-06T00:00:00Z"),
        _rev(4, 3, "A", "2026-09-01T00:00:00Z"),
    ]
    assert [r["revid"] for r in epd.select_scope(revs, "2026-08-01", "2026-08-31")] == [2, 3]
    assert [r["revid"] for r in epd.select_scope(revs, "2026-08-01", "2026-08-31", "A")] == [2]


def test_select_scope_end_is_inclusive_end_of_day():
    revs = [_rev(2, 1, "A", "2026-08-31T23:30:00Z")]
    assert len(epd.select_scope(revs, None, "2026-08-31")) == 1


# --- revids_to_measure ------------------------------------------------------ #
def test_revids_to_measure_includes_parents_excludes_zero():
    scoped = [_rev(2, 1, "A", "t"), _rev(5, 4, "B", "t"), _rev(1, 0, "A", "t")]
    assert epd.revids_to_measure(scoped) == {1, 2, 4, 5}  # parent 0 excluded


# --- aggregate_deltas ------------------------------------------------------- #
def test_aggregate_new_article_attributes_all_to_creator():
    scoped = [_rev(1, 0, "Creator", "t1")]
    per_rev, users, warn = epd.aggregate_deltas(scoped, {1: 120})
    assert warn == [] and per_rev[0]["words_delta"] == 120
    assert users[0].user == "Creator" and users[0].words_added == 120


def test_aggregate_reference_deltas_per_user():
    scoped = [
        _rev(1, 0, "A", "t1"),   # words +300, refs +2
        _rev(2, 1, "B", "t2"),   # words +200, refs +1
        _rev(3, 2, "A", "t3"),   # words -100, refs -1
    ]
    words = {1: 300, 2: 500, 3: 400}
    refs = {1: 2, 2: 3, 3: 2}
    _, users, _ = epd.aggregate_deltas(scoped, words, refs)
    by = {u.user: u for u in users}
    assert by["A"].refs_added == 2 and by["A"].refs_removed == 1 and by["A"].refs_net == 1
    assert by["B"].refs_added == 1 and by["B"].refs_net == 1


def test_aggregate_without_refs_map_does_not_warn():
    # refs are secondary — omitting the map must not create false warnings
    scoped = [_rev(1, 0, "A", "t1")]
    per_rev, users, warn = epd.aggregate_deltas(scoped, {1: 120})
    assert warn == []
    assert users[0].refs_added == 0 and per_rev[0]["refs_delta"] is None


def test_aggregate_gross_vs_net_and_multi_user():
    scoped = [
        _rev(1, 0, "A", "t1"),   # +300
        _rev(2, 1, "B", "t2"),   # +200
        _rev(3, 2, "A", "t3"),   # -100
    ]
    words = {1: 300, 2: 500, 3: 400}
    per_rev, users, _ = epd.aggregate_deltas(scoped, words)
    by = {u.user: u for u in users}
    assert by["A"].words_added == 300 and by["A"].words_removed == 100 and by["A"].words_net == 200
    assert by["B"].words_added == 200 and by["B"].words_net == 200
    assert [d["words_delta"] for d in per_rev] == [300, 200, -100]


def test_aggregate_unfetchable_revision_is_unmeasurable():
    scoped = [_rev(2, 1, "A", "t")]
    # rev 2 present, parent rev 1 missing from map (suppressed)
    per_rev, users, warn = epd.aggregate_deltas(scoped, {2: 90})
    assert per_rev[0]["words_delta"] is None
    assert users[0].unmeasured_edits == 1 and users[0].words_added == 0
    assert any("rev 1" in w for w in warn)


def test_aggregate_sorted_by_words_added():
    scoped = [_rev(1, 0, "Small", "t1"), _rev(2, 1, "Big", "t2")]
    _, users, _ = epd.aggregate_deltas(scoped, {1: 10, 2: 1000})
    assert [u.user for u in users] == ["Big", "Small"]
