"""Best-effort check for a newer release of this app on GitHub."""

import re
import urllib.request

REPO         = 'Stealthee/Blackshark-v3pro-guitray'
_PYPROJECT_URL = f'https://raw.githubusercontent.com/{REPO}/main/pyproject.toml'
RELEASES_URL = f'https://github.com/{REPO}'


def _parse_version(s):
    return tuple(int(p) for p in s.split('.'))


def check_for_update(current_version):
    """Return (latest_version, RELEASES_URL) if pyproject.toml on the
    repo's main branch declares a newer version than current_version,
    else None. Any network/parse failure is treated as "no update"."""
    try:
        with urllib.request.urlopen(_PYPROJECT_URL, timeout=5) as resp:
            text = resp.read().decode('utf-8', 'replace')
        m = re.search(r'^version\s*=\s*"([\d.]+)"', text, re.MULTILINE)
        if not m:
            return None
        latest = m.group(1)
        if _parse_version(latest) > _parse_version(current_version):
            return latest, RELEASES_URL
    except Exception:
        pass
    return None
