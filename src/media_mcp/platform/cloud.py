"""Cloud discovery and bounded, authenticated transfer of frozen download evidence."""
import base64
import hashlib
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from media_mcp.adapters.torrent import infohash
from media_mcp.application.acquire import MediaService
from media_mcp.platform.limits import Budget
from media_mcp.storage.records import Records, require_fresh


class Evidence(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Identity(Evidence):
    title_id: str = Field(pattern=r'^(movie|tv):[1-9][0-9]{0,11}$')
    kind: Literal['movie', 'tv']
    tmdb_id: int = Field(ge=1, le=999999999999)
    title: str = Field(min_length=1, max_length=1000)
    original_title: str | None = Field(default=None, max_length=1000)
    english_title: str | None = Field(default=None, max_length=1000)
    date: str | None = Field(default=None, max_length=20)
    original_language: str | None = Field(default=None, max_length=20)
    poster_url: str | None = Field(default=None, max_length=2048)
    rating: float | int | None = None
    rating_source: Literal['TMDB'] = 'TMDB'

    @model_validator(mode='after')
    def consistent(self):
        if self.title_id != f'{self.kind}:{self.tmdb_id}':
            raise ValueError('inconsistent_identity')
        return self


class Episode(Evidence):
    episode: int = Field(ge=1, le=999)
    title: str | None = Field(default=None, max_length=1000)


class Scope(Evidence):
    season: int | None = Field(default=None, ge=0, le=99)
    episodes: list[int] = Field(default_factory=list, max_length=200)
    resolution: Literal[480, 720, 1080, 2160] | None = None
    episode_metadata: list[Episode] = Field(default_factory=list, max_length=999)


class Release(Evidence):
    name: str = Field(min_length=1, max_length=1000)
    size: int | None = Field(default=None, ge=0)
    seeders: int | None = Field(default=None, ge=0)
    resolution: Literal[480, 720, 1080, 2160] | None = None
    indexer: str | None = Field(default=None, max_length=1000)
    indexer_id: str | None = Field(default=None, max_length=1000)
    categories: list[int] = Field(default_factory=list, max_length=100)
    download_url: str = Field(min_length=1, max_length=16384)
    claimed_infohash: str | None = Field(default=None, pattern=r'^[a-fA-F0-9]{40}$')


class Snapshot(Evidence):
    identity: Identity
    scope: Scope
    release: Release
    expires_at: float

    @model_validator(mode='after')
    def consistent(self):
        scope = self.scope
        if self.identity.kind == 'movie':
            if scope.season is not None or scope.episodes or scope.episode_metadata:
                raise ValueError('movie_has_no_episodes')
        elif (scope.season is None or not scope.episodes or
              not set(scope.episodes).issubset({e.episode for e in scope.episode_metadata})):
            raise ValueError('invalid_episode_scope')
        if any(type(e) is not int or not 1 <= e <= 999 for e in scope.episodes):
            raise ValueError('invalid_episode_scope')
        # The two hosts may differ slightly in time; still bound transferred lifetimes.
        if not time.time() < self.expires_at <= time.time()+2100:
            raise ValueError('snapshot_expired_search_again')
        return self


class Payload(Evidence):
    kind: Literal['bytes', 'magnet']
    data: str = Field(min_length=1, max_length=11184812)


class CloudRequest(Evidence):
    action: Literal['authorize', 'plan']
    operation: Literal['search_titles', 'search_releases', 'plan']
    release_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')
    snapshot: Snapshot | None = None
    payload: Payload | None = None


def decode_payload(payload, claimed=None):
    payload = Payload.model_validate(payload)
    if payload.kind == 'bytes':
        try:
            torrent = base64.b64decode(payload.data, validate=True)
        except ValueError:
            raise ValueError('invalid_torrent_payload') from None
        magnet = None
    else:
        if (len(payload.data) > 16384 or not payload.data.startswith('magnet:?')
                or any(ord(char) < 32 or ord(char) == 127 for char in payload.data)):
            raise ValueError('invalid_magnet_payload')
        torrent, magnet = None, payload.data
    actual = infohash(torrent, magnet)
    if claimed and claimed.lower() != actual:
        raise ValueError('indexer_infohash_mismatch')
    return torrent, magnet


class CloudRecords(Records):
    def __init__(self, db, owner):
        super().__init__(db)
        self.owner = owner

    def put(self, kind, data, *args, **kwargs):
        return super().put(kind, {**data, '_cloud_owner':self.owner}, *args, **kwargs)

    def get(self, ident, kind=None):
        row = super().get(ident, kind)
        if row['data'].get('_cloud_owner') != self.owner:
            raise ValueError('record_not_found')
        return row


class CloudCommands:
    operations = frozenset(('search_titles', 'search_releases', 'plan'))

    def __init__(self, call, db, tmdb, indexer):
        self.call, self.db, self.tmdb, self.indexer = call, db, tmdb, indexer
        Records(db).initialize()

    def invoke(self, operation, arguments):
        from media_mcp.platform.api import COMMANDS
        arguments = COMMANDS[operation].model_validate(arguments).model_dump()
        user = self.call({'action':'authorize', 'operation':operation})['user']
        with Budget(self.db).operation(user['id'], 'plan' if operation == 'plan' else 'search'):
            records = CloudRecords(self.db, user['id'])
            service = MediaService(records, self.tmdb, self.indexer)
            if operation != 'plan':
                return getattr(service, operation)(**arguments)
            row = records.get(arguments['release_id'], 'release')
            require_fresh(row['data'])
            snapshot = {k:row['data'][k] for k in ('identity','scope','release','expires_at')}
            url = snapshot['release']['download_url']
            content = self.indexer.torrent(url)
            payload = {'kind':'bytes', 'data':base64.b64encode(content).decode()} if isinstance(content, bytes) else {
                'kind':'magnet', 'data':content or url}
            decode_payload(payload, snapshot['release'].get('claimed_infohash'))
            return self.call({'action':'plan', 'operation':'plan', 'release_id':row['id'],
                              'snapshot':snapshot, 'payload':payload})


def accept_cloud(request, service):
    """Runs on NAS only after service and fresh user authorization."""
    if request.operation != 'search_titles':
        service._download_permission()
    if request.action == 'authorize':
        if any(value is not None for value in (request.snapshot,request.payload,request.release_id)):
            raise ValueError('invalid_request')
        from dataclasses import asdict
        if request.operation != 'plan':
            Budget(service.records.db,service.accounts.clock).charge(service.actor.id,'search')
        return {'user':asdict(service.actor)}
    if (request.operation != 'plan' or request.snapshot is None or request.payload is None
            or request.release_id is None):
        raise ValueError('invalid_request')
    data = request.snapshot.model_dump()
    decode_payload(request.payload.model_dump(), data['release'].get('claimed_infohash'))
    # Exclude the internal cloud URL: the local worker consumes these exact bytes/magnet.
    data['release']['download_url'] = 'cloud-prepared'
    data['cloud_payload'] = request.payload.model_dump()
    key = hashlib.sha256(('cloud-release:'+service.actor.id+':'+request.release_id).encode()).hexdigest()
    from media_mcp.runtime.state import media_mutation_lock
    with media_mutation_lock(service.records.db):
        row = service.records.by_key(key)
        if row:
            expected = {k:row['data'].get(k) for k in data}
            if expected != data:
                raise ValueError('cloud_release_changed_search_again')
        else:
            row = service.service.records.put('release', data, key_hash=key)
    return service.plan(row['id'])
