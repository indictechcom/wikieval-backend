"""Offline unit tests for services.article_engine (assembly orchestration).

The three sub-services are monkeypatched, so no network is used — these verify
the consolidated stats dict is assembled correctly.
"""

from services import article_engine as ae

_META = {
    "article_title": "Cat", "display_title": "Cat", "article_url": "https://x/Cat",
    "page_id": 6678, "revision_id": 100, "namespace": 0,
    "created_at": "2004-02-01T04:43:26Z", "creator": "Alice", "creator_id": 5,
    # process_article's word_count is already editor-authored prose (our counter)
    "byte_count": 5000, "word_count": 620,
    "ref_new_count": 3, "ref_reused_count": 1, "image_count": 2,
    "outgoing_links": 50, "incoming_links": 500,
}

_ANALYZE = {
    "revisions_fetched": 12, "revisions_in_scope": 12,
    "users": [
        {"user": "Alice", "edits": 3, "words_added": 620, "words_removed": 20,
         "words_net": 600, "unmeasured_edits": 0, "first_edit": "a", "last_edit": "b"},
        {"user": "Bob", "edits": 1, "words_added": 40, "words_removed": 0,
         "words_net": 40, "unmeasured_edits": 0, "first_edit": "c", "last_edit": "c"},
    ],
}


def _patch(monkeypatch, analyze_calls=None):
    monkeypatch.setattr(ae.mediawiki, "process_article",
                        lambda link, contest=None: dict(_META))
    monkeypatch.setattr(ae.editor_prose_counter, "title_from_link",
                        lambda link: ("https://en.wikipedia.org", "Cat"))
    monkeypatch.setattr(ae.editor_prose_counter, "fetch_namespace_names",
                        lambda base: (("Category",), ("File", "Image")))

    def fake_analyze(link, start=None, end=None, category_names=None, file_names=None):
        if analyze_calls is not None:
            analyze_calls.append((start, end))
        return dict(_ANALYZE)
    monkeypatch.setattr(ae.editor_prose_delta, "analyze", fake_analyze)


def test_snapshot_fields_and_editor_prose(monkeypatch):
    _patch(monkeypatch)
    s = ae.collect_article_stats("https://en.wikipedia.org/wiki/Cat")
    assert s["title"] == "Cat"
    assert s["page_id"] == 6678 and s["revision_id"] == 100 and s["namespace"] == 0
    assert s["created_at"] == "2004-02-01T04:43:26Z" and s["creator"] == "Alice"
    assert s["byte_count"] == 5000
    assert s["editor_prose_words"] == 620          # our metric, from the counter
    assert "word_count" not in s                   # XTools reader-prose not surfaced
    assert s["ref_new_count"] == 3 and s["image_count"] == 2
    assert s["outgoing_links"] == 50 and s["incoming_links"] == 500


def test_contributors_included_and_sorted(monkeypatch):
    _patch(monkeypatch)
    s = ae.collect_article_stats("https://en.wikipedia.org/wiki/Cat")
    assert s["total_revisions"] == 12
    assert s["editor_count"] == 2
    assert [c["user"] for c in s["contributions"]] == ["Alice", "Bob"]
    assert s["contributions"][0]["words_added"] == 620


def test_contributors_can_be_skipped(monkeypatch):
    _patch(monkeypatch)
    s = ae.collect_article_stats("https://x/Cat", include_contributors=False)
    assert "contributions" not in s and "total_revisions" not in s
    assert s["editor_prose_words"] == 620          # snapshot still present


def test_period_is_passed_through_to_analyze(monkeypatch):
    calls = []
    _patch(monkeypatch, analyze_calls=calls)
    s = ae.collect_article_stats("https://x/Cat", start="2026-08-01", end="2026-08-31")
    assert calls == [("2026-08-01", "2026-08-31")]
    assert s["contributions_period"] == {"start": "2026-08-01", "end": "2026-08-31"}
