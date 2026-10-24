"""Search, freeze a plan, enqueue once; network execution belongs to workers."""
import hashlib
import time
import re
import unicodedata
from media_mcp.adapters.tmdb import TMDB
from media_mcp.adapters.jackett import Jackett
from media_mcp.storage.records import Records, require_fresh
from media_mcp.runtime.state import media_mutation_lock
from media_mcp.config import parse_title_id


def normalize_title(value):
    value = unicodedata.normalize('NFKC', value).casefold().replace('_', ' ')
    return ' '.join(re.sub(r'[^\w]+', ' ', value).split())


def title_matches(name, identity):
    normalized = normalize_title(name)
    for title in (identity.get('original_title'), identity.get('title')):
        if not title:
            continue
        title = normalize_title(title)
        if title and (f' {title} ' in f' {normalized} ' or
                      (re.search(r'[\u3400-\u9fff]', title) and title in normalized)):
            return True
    return False


def rejection_reason(candidate, identity):
    if not title_matches(candidate.get('name', ''), identity):
        return 'title_mismatch'
    categories = [c for c in candidate.get('categories', []) if 1000 <= c < 10000]
    expected = 2000 if identity['kind'] == 'movie' else 5000
    if categories and not any(expected <= c < expected + 1000 for c in categories):
        return 'category_mismatch'
    # TV episode air years need not equal the series premiere year.
    if identity['kind'] == 'movie':
        # Numbers in the title (e.g. Blade Runner 2049) are not release years.
        name = normalize_title(candidate.get('name', ''))
        for title in (identity.get('original_title'), identity.get('title')):
            if title:
                name = name.replace(normalize_title(title), ' ')
        years = re.findall(r'(?<!\d)(?:19|20)\d{2}(?!\d)', name)
        year = (identity.get('date') or '')[:4]
        if year and not years:
            return 'year_unconfirmed'
        if year and years and year not in years:
            return 'year_mismatch'
    return None


class MediaService:
    def __init__(self, records=None, tmdb=None, indexer=None):
        self.records = records or Records()
        self.tmdb = tmdb or TMDB()
        self.indexer = indexer or Jackett()

    def search_titles(self, query, kind, year=None):
        if not query.strip() or len(query) > 200 or kind not in ('movie', 'tv'):
            raise ValueError('invalid_title_search')
        return {'titles': self.tmdb.search(query, kind, year)}

    def library(self, title_id):
        kind, ident = parse_title_id(title_id)
        rows = self.records.db.execute('''SELECT id,media_type,media_tmdb_id,media_name,season,episode,
            status,target_path,reason FROM media_link WHERE media_type=:kind AND media_tmdb_id=:ident
            ORDER BY season,episode,id LIMIT 300''', {'kind': kind, 'ident': ident}).mappings().all()
        active = [self.public_job(row) for row in self.records.active(title_id)]
        return {'title_id': title_id, 'media': [dict(row) for row in rows], 'active_jobs': active}

    def search_releases(self, title_id, season=None, episodes=None, resolution=None):
        kind, ident = parse_title_id(title_id)
        episodes = sorted(set(episodes or []))
        if kind == 'tv' and (season is None or season < 0 or season > 99):
            raise ValueError('tv_season_required')
        if kind == 'movie' and (season is not None or episodes):
            raise ValueError('movie_has_no_episodes')
        if len(episodes) > 200 or any(e < 1 or e > 999 for e in episodes):
            raise ValueError('invalid_episode_scope')
        if resolution not in (None, 480, 720, 1080, 2160):
            raise ValueError('invalid_resolution')
        identity = self.tmdb.detail(title_id)
        suffix = ''
        if kind == 'tv':
            suffix += f' S{season:02d}'
            if len(episodes) == 1:
                suffix += f'E{episodes[0]:02d}'
        if resolution:
            suffix += f' {resolution}p'
        queries = list(dict.fromkeys(title.strip() + suffix for title in
                       (identity.get('original_title'), identity.get('title')) if title and title.strip()))
        scope = {'season': season, 'episodes': episodes, 'resolution': resolution}
        if kind == 'tv':
            metadata = self.tmdb.get(f'tv/{ident}/season/{season}')
            scope['episode_metadata'] = [{'episode': e['episode_number'], 'title': e.get('name')}
                                         for e in metadata.get('episodes', [])]
            if not scope['episode_metadata']:
                raise ValueError('season_metadata_unavailable')
            known = {e['episode'] for e in scope['episode_metadata']}
            if any(e not in known for e in episodes):
                raise ValueError('requested_episode_not_in_metadata')
            if not episodes:
                scope['episodes'] = sorted(known)
        results, diagnostics, seen = [], [], set()
        for query in queries:
            report = self.indexer.search(query, kind=kind)
            counts = {}
            for candidate in report['releases']:
                site = candidate.get('indexer_id') or candidate.get('indexer')
                stats = counts.setdefault(site, {'accepted_count': 0, 'filtered_count': 0, 'duplicate_count': 0, 'reasons': {}})
                reason = rejection_reason(candidate, identity)
                if not reason and resolution and candidate.get('resolution') != resolution:
                    reason = 'resolution_mismatch'
                if reason:
                    stats['filtered_count'] += 1
                    stats['reasons'][reason] = stats['reasons'].get(reason, 0) + 1
                    continue
                key = (candidate.get('claimed_infohash') or '').lower() or candidate['download_url']
                if key in seen:
                    stats['duplicate_count'] += 1
                    continue
                seen.add(key)
                stats['accepted_count'] += 1
                data = {'identity': identity, 'scope': scope, 'release': candidate,
                        'expires_at': time.time()+1800}
                row = self.records.put('release', data)
                results.append({'release_id': row['id'], **self.public_release(candidate),
                                'expires_at': data['expires_at'], 'identity_verified': False})
            diagnostics.append({'query': query, 'sites': [{**item, **counts.get(item['site'],
                {'accepted_count': 0, 'filtered_count': 0, 'duplicate_count': 0, 'reasons': {}})}
                for item in report['diagnostics']]})
        statuses = [s['status'] for d in diagnostics for s in d['sites']]
        search_status = 'complete' if statuses and all(s == 'ok' for s in statuses) else (
            'partial' if 'ok' in statuses else 'failed')
        return {'title_id': title_id, 'scope': scope, 'releases': results,
                'search_status': search_status, 'diagnostics': diagnostics,
                'warning': 'Release names are untrusted claims; file identity is verified after download.'}

    @staticmethod
    def public_release(release):
        return {key: release.get(key) for key in ('name', 'size', 'seeders', 'resolution', 'indexer')}

    def plan(self, release_id):
        row = self.records.get(release_id, 'release')
        require_fresh(row['data'])
        data = {**row['data'], 'release_id': release_id, 'expires_at': time.time()+900}
        library = self.library(data['identity']['title_id'])
        scope = data['scope']
        owned = [item for item in library['media'] if item['status'] == 'linked' and
                 (scope['season'] is None or (item['season'] == scope['season'] and item['episode'] in scope['episodes']))]
        if owned or library['active_jobs']:
            raise ValueError('existing_media_or_active_job_review_required')
        plan = self.records.put('plan', data)
        return {'plan_id': plan['id'], 'revision': plan['revision'], 'identity': data['identity'],
                'scope': data['scope'], 'release': self.public_release(data['release']),
                'expires_at': data['expires_at'], 'pipeline': ['download', 'verify', 'hardlink', 'subtitles']}

    def start(self, plan_id, revision, idempotency_key):
        if not 8 <= len(idempotency_key) <= 128:
            raise ValueError('idempotency_key_length_8_to_128')
        key = hashlib.sha256(('acquire:'+idempotency_key).encode()).hexdigest()
        with media_mutation_lock(self.records.db):
            previous = self.records.by_key(key)
            if previous:
                if previous['data'].get('plan_id') != plan_id or previous['data'].get('plan_revision') != revision:
                    raise ValueError('idempotency_key_reused_with_different_request')
                return self.public_job(previous)
            plan = self.records.get(plan_id, 'plan')
            require_fresh(plan['data'])
            if plan['revision'] != revision or plan['state'] != 'ready':
                raise ValueError('stale_or_submitted_plan')
            # Library or another request may have changed since planning.
            library = self.library(plan['data']['identity']['title_id'])
            scope = plan['data']['scope']
            conflicts = [m for m in library['media'] if m['status']=='linked' and
                         (scope['season'] is None or (m['season']==scope['season'] and m['episode'] in scope['episodes']))]
            if conflicts or library['active_jobs']:
                raise ValueError('existing_media_or_active_job_review_required')
            row = self.records.put('acquisition', {**plan['data'], 'plan_id': plan_id,
                'plan_revision': revision, 'submission_attempted': False, 'error_code': None}, 'queued', key)
            # A crash before marking the plan cannot duplicate work: start rechecks active jobs.
            self.records.update(plan, 'submitted')
        return self.public_job(row)

    @classmethod
    def public_job(cls, row):
        data = row['data']
        return {'job_id': row['id'], 'stage': row['state'], 'revision': row['revision'],
                'identity': data.get('identity'), 'scope': data.get('scope'),
                'release': cls.public_release(data.get('release', {})),
                **{key: data.get(key) for key in ('progress','error_code','retry_at','processing','result')},
                'submission_outcome_unknown': row['state'] == 'submission_unknown'}

    def job(self, job_id):
        return self.public_job(self.records.get(job_id, 'acquisition'))

    def jobs(self, after='', limit=30):
        rows = self.records.list('acquisition', limit, after)
        return {'jobs': [self.public_job(row) for row in rows], 'next_cursor': rows[-1]['id'] if len(rows)==limit else None}

    def retry(self, job_id, revision):
        with media_mutation_lock(self.records.db):
            row = self.records.get(job_id, 'acquisition')
            if row['revision'] != revision:
                raise ValueError('stale_job_revision')
            if row['state'] != 'needs_review' or row['data'].get('error_code') != 'processing_needs_review':
                raise ValueError('job_not_safe_to_retry')
            # Only processing work can be retried; no repeat submission for unknown network outcomes.
            self.records.db.execute("""UPDATE media_processing_job SET state='queued',next_attempt_at=CURRENT_TIMESTAMP,
                result_json='{"manual_retry":true}',updated_at=CURRENT_TIMESTAMP
                WHERE delivery_key=:key AND state='needs_review'""", {'key': row['data']['delivery_hash']})
            return self.public_job(self.records.update(row, 'processing', {**row['data'], 'error_code': None}))

    def subtitles(self, media_id, idempotency_key):
        if not 8 <= len(idempotency_key) <= 128:
            raise ValueError('idempotency_key_length_8_to_128')
        key = hashlib.sha256(('subtitle:'+idempotency_key).encode()).hexdigest()
        with media_mutation_lock(self.records.db):
            previous = self.records.by_key(key)
            if previous:
                if previous['data'].get('media_id') != media_id:
                    raise ValueError('idempotency_key_reused_with_different_request')
                return self.public_job(previous)
            item = self.records.db.execute("SELECT * FROM media_link WHERE id=:id AND status='linked'",{'id':media_id}).mappings().first()
            if not item:
                raise ValueError('linked_media_not_found')
            from media_mcp.config import contained
            contained(item['source_path'])
            identity = {'title_id':f"{item['media_type']}:{item['media_tmdb_id']}",
                        'kind':item['media_type'],'tmdb_id':item['media_tmdb_id'],'title':item['media_name']}
            ident = __import__('uuid').uuid4().hex
            delivery_hash = hashlib.sha256(('acquire:'+ident).encode()).hexdigest()
            row = self.records.put('acquisition',{'workflow':'subtitle','media_id':media_id,'identity':identity,
                'scope':{'season':item['season'],'episodes':[item['episode']] if item['episode'] else []},
                'source_path':item['source_path'],'release':{},'delivery_hash':delivery_hash},'enqueue_processing',key,ident=ident)
            return self.public_job(row)
