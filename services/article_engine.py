"""article_engine.py — consolidated article statistics.

A single entry point that gathers everything known about an article in one call:
identity, creation/author, size, references, images, links, the editor-authored
prose word count, and a per-author contribution breakdown (who wrote how many
authored words).

It orchestrates three lower-level services:
  - services.mediawiki.process_article   — MediaWiki + XTools: identity, creation,
    author, byte size, references, images, in/out links.
  - services.editor_prose_counter        — editor-authored prose word count
    (wikitext, our contest metric — the reader-side XTools word count is not used).
  - services.editor_prose_delta          — per-user "authored words added" over
    the article's history (optionally scoped to a period).
"""

from services import editor_prose_counter, editor_prose_delta, mediawiki


def collect_article_stats(article_link, contest=None, include_contributors=True,
                          start=None, end=None):
    """Return a consolidated stats dict for an article.

    The snapshot fields always reflect the current revision. When
    `include_contributors` is True, the article's history is walked to attribute
    authored words per user (optionally scoped to the [start, end] period, e.g.
    a contest window). Dates are ISO strings (YYYY-MM-DD).
    """
    # process_article's "word_count" is already the editor-authored prose count
    # (services.mediawiki computes it with our counter — XTools is used only for
    # references and links there).
    meta = mediawiki.process_article(article_link, contest)

    stats = {
        # identity
        "title": meta.get("article_title"),
        "display_title": meta.get("display_title"),
        "article_url": meta.get("article_url"),
        "page_id": meta.get("page_id"),
        "revision_id": meta.get("revision_id"),
        "namespace": meta.get("namespace"),
        # creation / author
        "created_at": meta.get("created_at"),
        "creator": meta.get("creator"),
        "creator_id": meta.get("creator_id"),
        # size / content
        "byte_count": meta.get("byte_count"),
        "editor_prose_words": meta.get("word_count"),
        "ref_new_count": meta.get("ref_new_count"),
        "ref_reused_count": meta.get("ref_reused_count"),
        "image_count": meta.get("image_count"),
        "outgoing_links": meta.get("outgoing_links"),
        "incoming_links": meta.get("incoming_links"),
    }

    if include_contributors:
        base_url, _title = editor_prose_counter.title_from_link(article_link)
        category_names, file_names = editor_prose_counter.fetch_namespace_names(base_url)
        report = editor_prose_delta.analyze(
            article_link, start=start, end=end,
            category_names=category_names, file_names=file_names)
        stats["total_revisions"] = report["revisions_fetched"]
        stats["editor_count"] = len(report["users"])
        stats["contributions"] = report["users"]
        if start or end:
            stats["contributions_period"] = {"start": start, "end": end}

    return stats
