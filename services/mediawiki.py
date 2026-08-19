"""Article metadata for submissions.

`process_article` combines two sources:
- **MediaWiki API** — page creator/creation date, current byte size, namespace,
  exact revision id, and image count (`prop=images`).
- **XTools** — readable-prose word count, reference counts (total + unique), and
  full (uncapped) incoming/outgoing link counts.
"""

import urllib.parse

import requests

from services import editor_prose_counter

MEDIAWIKI_API_TIMEOUT = 10
XTOOLS_API_TIMEOUT = 30
USER_AGENT = "WikiEval/1.0 (https://wikieval.toolforge.org) Python/requests"

XTOOLS_API = "https://xtools.wmcloud.org/api/page"


def title_from_link(article_link):
    """Return (base_url, page_title) parsed from a MediaWiki article URL."""
    parsed = urllib.parse.urlparse(article_link)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    if "/wiki/" in parsed.path:
        title = parsed.path.split("/wiki/", 1)[1]
    elif "title=" in parsed.query:
        title = urllib.parse.parse_qs(parsed.query).get("title", [""])[0]
    else:
        title = parsed.path.rsplit("/", 1)[-1]
    return base_url, urllib.parse.unquote(title)


def process_article(article_link, contest=None):
    """Fetch article metadata. Raises ValueError if the title can't be parsed,
    the MediaWiki API is unreachable, or the article doesn't exist.

    XTools stats (words, refs, links) degrade to None if XTools is unavailable.
    `contest` is accepted for future contest-relative stats but unused here.
    """
    base_url, page_title = title_from_link(article_link)
    if not page_title:
        raise ValueError("Could not determine the article title from the link")

    try:
        response = requests.get(
            f"{base_url}/w/api.php",
            params={
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "prop": "revisions|info|images",
                "titles": page_title,
                "rvprop": "timestamp|user|userid",
                "rvlimit": "1",
                "rvdir": "newer",            # oldest revision first == page creator
                "inprop": "displaytitle|url",
                "imlimit": "500",            # files embedded on the page (images)
                "redirects": "true",
                "converttitles": "true",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=MEDIAWIKI_API_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as error:
        raise ValueError(f"Could not fetch article from MediaWiki: {error}")

    pages = data.get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing"):
        raise ValueError("Article not found")

    page = pages[0]
    creation = (page.get("revisions") or [{}])[0]   # first (oldest) revision
    resolved_title = page.get("title", page_title)

    # References and (uncapped) link counts come from XTools; the word count is
    # our own editor-authored prose counter (not XTools' readable-prose count).
    prose = _xtools("prose", base_url, resolved_title)
    links = _xtools("links", base_url, resolved_title)
    references = prose.get("references")
    unique_refs = prose.get("unique_references")
    reused_refs = (
        references - unique_refs
        if references is not None and unique_refs is not None else None
    )

    return {
        "article_title": resolved_title,
        "display_title": page.get("displaytitle"),
        "article_url": page.get("fullurl", article_link),
        "page_id": page.get("pageid"),
        "revision_id": page.get("lastrevid"),        # pins the exact version
        "namespace": page.get("ns"),                 # 0 == main (article) namespace
        "byte_count": page.get("length"),            # full article size (prop=info)
        "word_count": _editor_prose_word_count(base_url, page.get("lastrevid")),
        "creator": creation.get("user"),             # first revision author
        "creator_id": creation.get("userid"),
        "created_at": creation.get("timestamp"),     # first revision timestamp
        "ref_new_count": unique_refs,                # unique/defining references
        "ref_reused_count": reused_refs,             # total - unique
        # Files embedded on the page (prop=images) — catches bracketed links,
        # infobox/template params, and galleries; may include decorative files.
        "image_count": len(page.get("images", [])),
        "outgoing_links": links.get("links_out_count"),  # full count (XTools)
        "incoming_links": links.get("links_in_count"),   # full count (XTools)
    }


def _editor_prose_word_count(base_url, revid):
    """Editor-authored prose word count of a revision (our own counter, not
    XTools). Returns None if the revision's wikitext can't be fetched, matching
    the eligibility flow's "word count unavailable -> try again" behaviour."""
    if not revid:
        return None
    try:
        cats, files = editor_prose_counter.fetch_namespace_names(base_url)
        counts = editor_prose_counter.count_revisions_words(base_url, [revid], cats, files)
        return counts.get(revid)
    except requests.RequestException:
        return None


def _xtools(endpoint, base_url, page_title):
    """Call an XTools page API endpoint; return its JSON dict, or {} on failure."""
    domain = urllib.parse.urlparse(base_url).netloc
    title = urllib.parse.quote(page_title.replace(" ", "_"), safe="")
    try:
        response = requests.get(
            f"{XTOOLS_API}/{endpoint}/{domain}/{title}",
            headers={"User-Agent": USER_AGENT},
            timeout=XTOOLS_API_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError):
        return {}
