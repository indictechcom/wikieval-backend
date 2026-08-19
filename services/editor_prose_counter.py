#!/usr/bin/env python3
"""editor_prose_counter.py — "editor-authored prose" word counter (wikitext).

A contest-side counter: it counts the words an *editor actually wrote*, not what
the page renders for a *reader*. So it is computed from **wikitext** (no HTML
render) and deliberately EXCLUDES content the editor did not author as prose:

  excluded : templates (banners, infoboxes, citations, {{convert}}, {{lang}} …),
             <ref>…</ref> content, category links, tables
  included : plain prose, wikilink / external-link display text, bold/italic,
             section headings, image captions

Rationale: a `{{banner}}` an editor typed in 8 characters should score ~0, not
the 500 words it renders. This is the opposite of the reader-side readable-prose
count (prose_counter.py / XTools / Prosesize), and it is intentionally our own
metric — no external tool measures it, so it is validated by definition + unit
tests + delta consistency rather than by benchmarking.

Fast: wikitext is fetched in batches of up to 50 revisions per request and
parsed in milliseconds — no per-revision rendering. Ideal for scoring many
revisions of an edit-a-thon article.

Known limitation: image *format* options (thumb/right/250px …) are recognised in
their English canonical form. On non-English wikis, localized format magic words
may leak ~1 token per image into a caption. Namespace names for Category/File
ARE resolved per-wiki (siteinfo), so category/file links are stripped correctly.

"""

import re
import urllib.parse

import mwparserfromhell
import requests

USER_AGENT = "WikiEval-EditorProse/1.0 (https://wikieval.toolforge.org) Python/requests"
HTTP_TIMEOUT = 20
REVIDS_PER_REQUEST = 50

# A real word must contain a word character (letter/digit, any script) and no
# wikitext structural markup. The word-char rule drops stray "." "," "—" left by
# stripped templates; the structural-char rule is a safety net that drops any
# raw markup ({{ | ]] = or a bare URL) that leaked from genuinely malformed
# wikitext that mwparserfromhell could not parse.
_WORD_CHAR = re.compile(r"\w", re.UNICODE)
_NONWORD = re.compile(r"[{}\[\]|=]|://")
# Punctuation that separates words when the editor omitted the space — parens,
# comma, semicolon, !/?, double quotes/guillemets, ellipsis, and the Indic danda
# ।॥. Deliberately EXCLUDED: apostrophe/hyphen/period (keep "don't", "well-known",
# "U.S.A.", "3.14" whole) and colon/slash (keep "10:30", "km/h", and — crucially
# — bare URLs whole so "http://…" is dropped by the :// rule rather than split).
_WORD_SEP = re.compile(r"[(),;!?\"“”«»…।॥]")
# behaviour switches / magic words: __TOC__, __NOTOC__, __NOEDITSECTION__, …
_MAGIC_WORD = re.compile(r"__[A-Z]+__")
_REDIRECT = re.compile(r"^\s*#\s*redirect\b", re.IGNORECASE)
# A line beginning with table syntax ({| |} |- |+ | !) is a table row/cell —
# stripped whole. mwparserfromhell mis-parses complex (rowspan/colspan) and
# template-opened tables, so their cell data would otherwise leak as prose.
# Prose never starts a line with these; multiline template params also start
# with "|" but their template is excluded anyway, so removing them is safe.
_TABLE_LINE = re.compile(r"^\s*(\{\||[|!])")
# lowercase, colon-prefixed, display-less wikilink => interlanguage/interwiki
# link (e.g. [[de:Katze]]); standard namespaces are capitalised so are safe.
_LANG_PREFIX = re.compile(r"^[a-z][a-z0-9-]*$")
# A citation <ref> — both <ref>…</ref> and self-closing <ref …/>. The \b after
# "ref" means <references/> (the list container) is NOT counted.
_REF_OPEN = re.compile(r"<ref\b", re.IGNORECASE)
# tags whose contents are not editor prose (references, code, formulae, media).
# refs are removed here (via the parsed tree) rather than by regex — a regex
# <ref>…</ref> strip can unbalance braces and break template parsing.
NONPROSE_TAGS = {
    "ref", "references", "table", "syntaxhighlight", "source", "pre", "code",
    "nowiki", "math", "chem", "ce", "score", "timeline", "hiero", "gallery",
    "mapframe", "maplink",
}
# English canonical image format options; anything else in a File link is caption.
_IMG_OPT = re.compile(
    r"^\s*(thumb|thumbnail|frame|frameless|border|right|left|centre|center|none"
    r"|upright|baseline|middle|sub|super|text-top|text-bottom|top|bottom"
    r"|\d+\s*px|x\d+\s*px|\d+x\d+\s*px)\s*$", re.IGNORECASE)

DEFAULT_CATEGORY_NAMES = ("Category",)
DEFAULT_FILE_NAMES = ("File", "Image")


def _strip_table_lines(wikitext):
    """Drop wikitable rows/cells — lines starting with {| |} |- |+ | ! — but
    only when *outside* a template (brace-depth 0). Inside a template such a
    line is a parameter (kept; the whole template is excluded later), so this
    never unbalances template braces. Handles complex (rowspan/colspan) and
    template-opened tables that mwparserfromhell mis-parses."""
    out = []
    depth = 0
    for line in wikitext.split("\n"):
        if depth <= 0 and _TABLE_LINE.match(line):
            pass  # table row/cell outside any template — drop it
        else:
            out.append(line)
        depth += line.count("{{") - line.count("}}")
    return "\n".join(out)


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


def _caption_of(link):
    """The caption of a File/Image wikilink — its last free-text parameter,
    with image format options and named params (alt=, link=, …) dropped."""
    if link.text is None:
        return ""
    keep = []
    for part in str(link.text).split("|"):
        s = part.strip()
        if not s or _IMG_OPT.match(s):
            continue
        if "=" in s.split(" ", 1)[0]:  # named param: alt=, link=, upright=1.2
            continue
        keep.append(part)
    return keep[-1] if keep else ""


def editor_prose_text(wikitext, category_names=DEFAULT_CATEGORY_NAMES,
                      file_names=DEFAULT_FILE_NAMES):
    """Return the editor-authored prose text (markup stripped).

    Excludes templates, <ref> content, category links, tables, code/media tags,
    magic words and bare interlanguage links; includes headings and image
    captions. `category_names`/`file_names` are the wiki's namespace names
    (localized + canonical) — see fetch_namespace_names(). editor_prose_words()
    counts the word-tokens of this text.
    """
    if not wikitext or _REDIRECT.match(wikitext):
        return ""  # a redirect has no authored prose
    # Line-strip tables and magic words (both brace-safe). Refs and templates
    # are removed via the parsed tree below, not by regex, to keep braces
    # balanced (a regex <ref> strip once unbalanced infobox braces).
    code = mwparserfromhell.parse(_MAGIC_WORD.sub(" ", _strip_table_lines(wikitext)))
    cats = {c.lower() for c in category_names}
    files = {f.lower() for f in file_names}

    for link in list(code.filter_wikilinks()):
        title = str(link.title)
        prefix = title.split(":", 1)[0].strip()
        ns = prefix.lower()
        if ns in cats:
            try:
                code.remove(link)
            except ValueError:
                pass
        elif ns in files:  # keep only the caption
            caption = _caption_of(link)
            try:
                code.replace(link, mwparserfromhell.parse(caption) if caption else "")
            except ValueError:
                pass
        elif link.text is None and ":" in title and _LANG_PREFIX.match(prefix):
            try:  # bare interlanguage/interwiki link, e.g. [[de:Katze]]
                code.remove(link)
            except ValueError:
                pass

    for tag in code.filter_tags():
        if str(getattr(tag, "tag", "")).strip().lower() in NONPROSE_TAGS:
            try:
                code.remove(tag)
            except ValueError:
                pass

    return code.strip_code(normalize=True, collapse=True)


def editor_prose_words(wikitext, category_names=DEFAULT_CATEGORY_NAMES,
                       file_names=DEFAULT_FILE_NAMES):
    """Count editor-authored prose words in a revision's wikitext.

    Drops whitespace tokens carrying raw markup residue ({{ | ]] = or a bare
    URL), then splits punctuation-joined words (e.g. "college(own" → 2) before
    counting. A word must contain at least one word-character.
    """
    text = editor_prose_text(wikitext, category_names, file_names)
    words = (w.strip("=") for w in _WORD_SEP.sub(" ", text).split())
    # strip("=") removes stray heading markers left by a MALFORMED heading
    # (e.g. "==X=" leaks "=X") so the word still counts; a token with an
    # *internal* "=" (or other markup) is attribute residue and is dropped.
    return sum(1 for w in words if w and _WORD_CHAR.search(w) and not _NONWORD.search(w))


def count_references(wikitext):
    """Number of <ref> citations in a revision's wikitext — both defined
    (<ref>…</ref>) and reused (<ref name=… />). Excludes the <references/> list
    container. Used for per-contributor reference deltas, counted from what the
    editor wrote (consistent with the word counter)."""
    if not wikitext:
        return 0
    return len(_REF_OPEN.findall(wikitext))


# --------------------------------------------------------------------------- #
# Wiki access
# --------------------------------------------------------------------------- #
def fetch_namespace_names(base_url):
    """(category_names, file_names) for a wiki — localized name + canonical
    aliases + namespacealiases — so category/file links strip correctly."""
    data = requests.get(
        f"{base_url}/w/api.php",
        params={"action": "query", "meta": "siteinfo",
                "siprop": "namespaces|namespacealiases",
                "format": "json", "formatversion": "2"},
        headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT,
    ).json()["query"]
    ns = data["namespaces"]
    cats = {ns["14"]["name"], "Category"}
    files = {ns["6"]["name"], "File", "Image"}
    for alias in data.get("namespacealiases", []):
        if alias.get("id") == 14:
            cats.add(alias["alias"])
        elif alias.get("id") == 6:
            files.add(alias["alias"])
    return tuple(cats), tuple(files)


def fetch_wikitext_batch(base_url, revids):
    """Map revid → wikitext, fetched in batches of REVIDS_PER_REQUEST."""
    out = {}
    revids = [r for r in revids if r]
    for i in range(0, len(revids), REVIDS_PER_REQUEST):
        chunk = revids[i:i + REVIDS_PER_REQUEST]
        data = requests.get(
            f"{base_url}/w/api.php",
            params={"action": "query", "format": "json", "formatversion": "2",
                    "prop": "revisions", "revids": "|".join(str(r) for r in chunk),
                    "rvprop": "ids|content", "rvslots": "main"},
            headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT,
        ).json()
        for page in data.get("query", {}).get("pages", []):
            for rev in page.get("revisions", []):
                content = (rev.get("slots", {}).get("main", {}) or {}).get("content")
                out[rev["revid"]] = content or ""
    return out


def count_revisions_words(base_url, revids, category_names=None, file_names=None):
    """Map revid → editor-prose word count for many revisions (batched)."""
    if category_names is None or file_names is None:
        category_names, file_names = fetch_namespace_names(base_url)
    contents = fetch_wikitext_batch(base_url, revids)
    return {rid: editor_prose_words(wt, category_names, file_names)
            for rid, wt in contents.items()}


def latest_revid(base_url, title):
    data = requests.get(
        f"{base_url}/w/api.php",
        params={"action": "query", "format": "json", "formatversion": "2",
                "prop": "revisions", "titles": title, "rvprop": "ids", "rvlimit": "1"},
        headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT,
    ).json()
    page = data.get("query", {}).get("pages", [{}])[0]
    revs = page.get("revisions", [])
    return None if page.get("missing") or not revs else revs[0]["revid"]
