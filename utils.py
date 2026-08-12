import requests


def getHeader():
    agent = 'WikiEval/1.0 (https://wikicontest.toolforge.org; 0freerunning@gmail.com)'
    return {
        'User-Agent': agent
    }

def get_wikimedia_edit_count(username, base_url='https://meta.wikimedia.org/w'):
    """
    Fetch a user's GLOBAL edit count across all Wikimedia projects
    (Wikipedia, Commons, Wikidata, Wikisource, etc.) using CentralAuth's
    globaluserinfo API. This reflects the user's real overall contribution
    level, not just their activity on meta.wikimedia.org.

    Args:
        username: Wikimedia username to look up
        base_url: Wiki API base URL (any wiki works, since globaluserinfo
                  is centralized via CentralAuth — meta is a safe default)

    Returns:
        int: global edit count, or None if it couldn't be determined
    """
    api_url = f"{base_url}/api.php"
    params = {
        'action': 'query',
        'meta': 'globaluserinfo',
        'guiuser': username,
        'guiprop': 'editcount',
        'format': 'json',
        'formatversion': '2',
    }

    try:
        response = requests.get(
            api_url,
            params=params,
            headers=getHeader(),
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        global_info = data.get('query', {}).get('globaluserinfo', {})
        return global_info.get('editcount')

    except (requests.RequestException, ValueError, KeyError):
        return None

def get_article_info(article_url):
    """
    Fetch an article's title, byte size, and reference count from its
    MediaWiki API, given the full article URL (e.g.
    https://en.wikipedia.org/wiki/Some_Article).

    Returns:
        dict: {
            "title": str or None,
            "byte_count": int or None,
            "reference_count": int or None,
            "exists": bool,
        }
        or None if the URL couldn't be parsed / the API call failed entirely.
    """
    from urllib.parse import urlparse, unquote
    import re

    parsed = urlparse(article_url)
    if not parsed.scheme or not parsed.netloc:
        return None

    # Extract page title from a standard /wiki/Page_Title URL
    match = re.search(r'/wiki/([^?#]+)', parsed.path)
    if not match:
        return None

    page_title = unquote(match.group(1))
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    api_url = f"{base_url}/w/api.php"

    params = {
        'action': 'query',
        'titles': page_title,
        'prop': 'revisions|extlinks',
        'rvprop': 'size',
        'rvslots': 'main',
        'ellimit': 'max',
        'format': 'json',
        'formatversion': '2',
    }

    try:
        response = requests.get(
            api_url,
            params=params,
            headers=getHeader(),
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        pages = data.get('query', {}).get('pages', [])
        if not pages:
            return {"title": None, "byte_count": None, "reference_count": None, "exists": False}

        page = pages[0]
        if page.get('missing'):
            return {"title": page.get('title'), "byte_count": None, "reference_count": None, "exists": False}

        title = page.get('title')

        revisions = page.get('revisions', [])
        byte_count = revisions[0].get('size') if revisions else None

        # extlinks gives us a rough external-reference count.
        # (Full <ref> tag counting would need wikitext parsing — out of
        # scope for this simple pre-validation check.)
        extlinks = page.get('extlinks', [])
        reference_count = len(extlinks)

        return {
            "title": title,
            "byte_count": byte_count,
            "reference_count": reference_count,
            "exists": True,
        }

    except (requests.RequestException, ValueError, KeyError, IndexError):
        return None        