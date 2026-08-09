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