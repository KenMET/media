"""Conservative release coverage claims; physical identity is checked after download."""
from datetime import date, datetime, timezone
import re
from media_mcp.ingest.domain.quality import release_quality_claim


def coverage(name, season, expected):
    text = name.casefold()
    seasons = {int(n) for n in re.findall(r'(?<![a-z0-9])s(\d{1,2})(?!\d)', text)}
    seasons.update(int(n) for n in re.findall(r'\u7b2c\s*(\d{1,2})\s*\u5b63', text))
    if seasons and seasons != {season}:
        return 'other_season', []
    if re.search(r's\d{1,2}e\d{1,3}(?:e\d{1,3})+',text):
        return 'unknown', []
    episodes = set()
    for match in re.finditer(r's(\d{1,2})e(\d{1,3})(?:\s*[-~]\s*(?:s\d{1,2})?e?(\d{1,3}))?', text):
        if int(match[1]) != season:
            return 'other_season', []
        start, end = int(match[2]), int(match[3] or match[2])
        if not 1 <= start <= end <= 999:
            return 'unknown', []
        episodes.update(range(start, end+1))
    if episodes:
        selected = sorted(episodes & set(expected))
        return ('episode' if len(episodes) == 1 else 'season_pack' if set(expected).issubset(episodes) else 'partial_pack'), selected
    if seasons == {season}:
        return 'season_pack', sorted(expected)
    return 'unknown', []


def season_scope(metadata, requested, today=None):
    today = today or datetime.now(timezone.utc).date()
    rows = metadata.get('episodes', [])
    known = {e['episode_number'] for e in rows}
    if not known:
        raise ValueError('season_metadata_unavailable')
    if set(requested)-known:
        raise ValueError('requested_episode_not_in_metadata')
    available = []
    for episode in rows:
        air = episode.get('air_date')
        try:
            if air and date.fromisoformat(air) > today:
                continue
        except (TypeError, ValueError):
            continue
        available.append(episode['episode_number'])
    selected = sorted(set(requested) if requested else set(available))
    if requested and set(requested)-set(available):
        raise ValueError('requested_episode_not_aired')
    if not selected:
        raise ValueError('no_aired_episodes')
    return selected, sorted(known)


def release_rank(release, *, explicit=False):
    claim=release_quality_claim(release.get('name',''))
    order = {'episode':0, 'partial_pack':1, 'season_pack':2, 'unknown':3} if explicit else {'season_pack':0, 'partial_pack':1, 'episode':2, 'unknown':3}
    return (int(release.get('seeders') == 0), order.get(release.get('coverage_kind'), 4),
            -(claim['source_rank'] or 0), -claim['revision'], -(release.get('seeders') or 0), -(release.get('size') or 0))


def select_releases(releases, wanted):
    """Prefer a complete available pack, then cover missing episodes without overlap."""
    remaining = set(wanted)
    selected = []
    for release in sorted(releases, key=release_rank):
        covered = set(release.get('covered_episodes', [])) & remaining
        if not covered or release.get('seeders') == 0:
            continue
        selected.append((release, sorted(covered)))
        remaining -= covered
        if not remaining:
            break
    return selected, sorted(remaining)
