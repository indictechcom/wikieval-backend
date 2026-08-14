import urllib.parse

import mwparserfromhell
import requests

MEDIAWIKI_API_TIMEOUT = 10
USER_AGENT = "WikiEval/1.0 (https://wikieval.toolforge.org) Python/requests"

# Cap link counts at one page (500) so each is a single API call. Popular
# articles report 500 (a floor); contest submissions are typically well under.
MAX_LINKS = 500


def title_from_link(article_link):
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

    # References come from the latest wikitext (one more call).
    wikitext = _fetch_wikitext(base_url, page_title)
    new_refs, reused_refs = _count_references(wikitext)
    resolved_title = page.get("title", page_title)

    return {
        "article_title": resolved_title,
        "display_title": page.get("displaytitle"),
        "article_url": page.get("fullurl", article_link),
        "page_id": page.get("pageid"),
        "revision_id": page.get("lastrevid"),       # pins the exact version
        "namespace": page.get("ns"),                # 0 == main (article) namespace
        "byte_count": page.get("length"),           # current size, from prop=info
        "creator": creation.get("user"),            # first revision author
        "creator_id": creation.get("userid"),
        "created_at": creation.get("timestamp"),    # first revision timestamp
        "ref_new_count": new_refs,
        "ref_reused_count": reused_refs,
        # Files embedded on the page (prop=images) — catches bracketed links,
        # infobox/template params, and galleries (prefixed or bare). Capped at
        # imlimit=500; may include decorative template files.
        "image_count": len(page.get("images", [])),
        "outgoing_links": _count_outgoing_links(base_url, resolved_title),
        "incoming_links": _count_incoming_links(base_url, resolved_title),
    }


def _fetch_wikitext(base_url, page_title):
    try:
        response = requests.get(
            f"{base_url}/w/api.php",
            params={
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "prop": "revisions",
                "titles": page_title,
                "rvprop": "content",
                "rvslots": "main",
                "rvlimit": "1",
                "redirects": "true",
                "converttitles": "true",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=MEDIAWIKI_API_TIMEOUT,
        )
        response.raise_for_status()
        pages = response.json().get("query", {}).get("pages", [])
    except requests.RequestException:
        return ""
    if not pages:
        return ""
    revision = (pages[0].get("revisions") or [{}])[0]
    return revision.get("slots", {}).get("main", {}).get("content", "") or ""


def _count_references(wikitext):
    new_refs = reused_refs = 0
    for tag in mwparserfromhell.parse(wikitext or "").filter_tags():
        if str(tag.tag).strip().lower() == "ref":
            if tag.self_closing:
                reused_refs += 1
            else:
                new_refs += 1
    return new_refs, reused_refs


def _count_outgoing_links(base_url, page_title):
    count, cont = 0, {}
    while count < MAX_LINKS:
        params = {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "prop": "links",
            "titles": page_title,
            "plnamespace": "0",          # mainspace links only
            "pllimit": "500",
            "redirects": "true",
            "converttitles": "true",
        }
        params.update(cont)
        try:
            response = requests.get(
                f"{base_url}/w/api.php", params=params,
                headers={"User-Agent": USER_AGENT}, timeout=MEDIAWIKI_API_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException:
            break
        pages = data.get("query", {}).get("pages", [])
        if pages:
            count += len(pages[0].get("links", []))
        cont = data.get("continue")
        if not cont:
            break
    return count


def _count_incoming_links(base_url, page_title):
    count, cont = 0, {}
    while count < MAX_LINKS:
        params = {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "list": "backlinks",
            "bltitle": page_title,
            "blnamespace": "0",              # mainspace only
            "bllimit": "500",
            "blfilterredir": "nonredirects",  # ignore redirect pages
        }
        params.update(cont)
        try:
            response = requests.get(
                f"{base_url}/w/api.php", params=params,
                headers={"User-Agent": USER_AGENT}, timeout=MEDIAWIKI_API_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException:
            break
        count += len(data.get("query", {}).get("backlinks", []))
        cont = data.get("continue")
        if not cont:
            break
    return count


