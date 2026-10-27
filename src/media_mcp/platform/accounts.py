"""Local account/session persistence; raw passwords and session tokens are never stored."""
from dataclasses import dataclass
import hashlib
import hmac
import re
import secrets
import time
import uuid

from sqlalchemy import text

from media_mcp.storage.client import DatabaseClient


@dataclass(frozen=True)
class Actor:
    id: str
    username: str
    role: str
    can_download: bool = True
    can_manage_media: bool = False

    def __post_init__(self):
        if self.admin:
            object.__setattr__(self, 'can_download', True)
            object.__setattr__(self, 'can_manage_media', True)

    @property
    def admin(self):
        return self.role == 'admin'


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt=None):
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValueError('password_requires_12_to_256_characters')
    salt = salt or secrets.token_hex(16)
    hashed = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f'scrypt${salt}${hashed}'


def verify_password(password, saved):
    try:
        algorithm, salt, _ = saved.split('$')
        return algorithm == 'scrypt' and hmac.compare_digest(password_hash(password, salt), saved)
    except (ValueError, TypeError):
        return False


class Accounts:
    def __init__(self, db=None, clock=time.time):
        self.db = db or DatabaseClient()
        self.clock = clock

    def initialize(self):
        with self.db.lock('platform-schema', timeout=10):
            for statement in (
                '''CREATE TABLE IF NOT EXISTS platform_user (
                    id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL, role TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1, auth_version INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL)''',
                '''CREATE TABLE IF NOT EXISTS platform_session (
                    token_hash TEXT PRIMARY KEY, csrf_hash TEXT NOT NULL, user_id TEXT NOT NULL,
                    auth_version INTEGER NOT NULL, expires_at REAL NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES platform_user(id))''',
                '''CREATE TABLE IF NOT EXISTS platform_login_attempt (
                    key_hash TEXT PRIMARY KEY, failures INTEGER NOT NULL, reset_at REAL NOT NULL)''',
                '''CREATE TABLE IF NOT EXISTS platform_api_token (
                    id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, user_id TEXT NOT NULL,
                    auth_version INTEGER NOT NULL, name TEXT NOT NULL, expires_at REAL NOT NULL,
                    created_at REAL NOT NULL, FOREIGN KEY(user_id) REFERENCES platform_user(id))''',
                '''CREATE TABLE IF NOT EXISTS platform_access (
                    kind TEXT NOT NULL, object_id TEXT NOT NULL, user_id TEXT NOT NULL,
                    permission TEXT NOT NULL, PRIMARY KEY(kind,object_id,user_id),
                    FOREIGN KEY(user_id) REFERENCES platform_user(id))''',
                '''CREATE TABLE IF NOT EXISTS platform_event (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id TEXT NOT NULL,
                    action TEXT NOT NULL, kind TEXT NOT NULL, object_id TEXT NOT NULL,
                    subject_id TEXT, created_at REAL NOT NULL)''',
            ):
                self.db.execute(statement)
            # Existing users retain their download access, never gain global media management.
            for name, default in (('can_download', 1), ('can_manage_media', 0)):
                if not self.db.column_exists('platform_user', name):
                    self.db.execute(f'ALTER TABLE platform_user ADD COLUMN {name} INTEGER NOT NULL DEFAULT {default}')

    @staticmethod
    def _actor(row):
        return Actor(row['id'], row['username'], row['role'],
                     bool(row['can_download']), bool(row['can_manage_media']))

    @staticmethod
    def validate_username(username):
        if not isinstance(username, str) or not re.fullmatch(r'[a-zA-Z0-9_.-]{3,48}', username):
            raise ValueError('invalid_username')
        return username.lower()

    def bootstrap(self, username, password, supplied_token, expected_token):
        if not expected_token or len(expected_token) < 32 or not hmac.compare_digest(
                digest(supplied_token), digest(expected_token)):
            raise ValueError('bootstrap_denied')
        username = self.validate_username(username)
        saved = password_hash(password)
        ident = uuid.uuid4().hex
        with self.db.begin() as conn:
            if conn.execute(text('SELECT COUNT(*) FROM platform_user')).scalar():
                raise ValueError('bootstrap_closed')
            conn.execute(text('''INSERT INTO platform_user
                (id,username,password_hash,role,created_at) VALUES(:id,:name,:password,'admin',:now)'''),
                {'id':ident, 'name':username, 'password':saved, 'now':self.clock()})
        return Actor(ident, username, 'admin')

    def login(self, username, password, peer='local'):
        # Both peer and account are rate limited; changing the username cannot evade the peer limit.
        now = self.clock()
        normalized = str(username).lower()[:48]
        buckets = (digest('peer:'+peer), digest('user:'+normalized))
        with self.db.begin() as conn:
            conn.execute(text('DELETE FROM platform_login_attempt WHERE reset_at<=:now'), {'now':now})
            for key in buckets:
                row = conn.execute(text('SELECT failures FROM platform_login_attempt WHERE key_hash=:key'),
                                   {'key':key}).first()
                if row and row[0] >= 10:
                    raise ValueError('login_rate_limited')
            # Reserve an attempt before the expensive hash, including successful attempts.
            for key in buckets:
                conn.execute(text('''INSERT INTO platform_login_attempt(key_hash,failures,reset_at)
                    VALUES(:key,1,:reset) ON CONFLICT(key_hash) DO UPDATE SET failures=failures+1'''),
                    {'key':key, 'reset':now+900})
        row = self.db.execute('SELECT * FROM platform_user WHERE username=:name',
                              {'name':normalized}).mappings().first()
        dummy = 'scrypt$' + '00'*16 + '$' + '00'*64
        valid = verify_password(password, row['password_hash'] if row else dummy)
        if not row or not row['enabled'] or not valid:
            raise ValueError('invalid_credentials')
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.db.begin() as conn:
            current = conn.execute(text('SELECT enabled,auth_version FROM platform_user WHERE id=:id'),
                                   {'id':row['id']}).mappings().one()
            if not current['enabled'] or current['auth_version'] != row['auth_version']:
                raise ValueError('invalid_credentials')
            conn.execute(text('DELETE FROM platform_session WHERE expires_at<=:now'), {'now':now})
            conn.execute(text('''INSERT INTO platform_session
                (token_hash,csrf_hash,user_id,auth_version,expires_at) VALUES(:token,:csrf,:id,:version,:expiry)'''),
                {'token':digest(token), 'csrf':digest(csrf), 'id':row['id'],
                 'version':row['auth_version'], 'expiry':now+43200})
            for key in buckets:
                conn.execute(text('UPDATE platform_login_attempt SET failures=MAX(0,failures-1) WHERE key_hash=:key'),
                             {'key':key})
        return token, csrf, self._actor(row)

    def authenticate(self, token, csrf=None):
        row = self.db.execute('''SELECT u.*,s.csrf_hash FROM platform_session s
            JOIN platform_user u ON u.id=s.user_id WHERE s.token_hash=:token
            AND s.expires_at>:now AND s.auth_version=u.auth_version AND u.enabled=1''',
            {'token':digest(token), 'now':self.clock()}).mappings().first()
        if not row:
            raise ValueError('authentication_required')
        if csrf is not None and not hmac.compare_digest(digest(csrf), row['csrf_hash']):
            raise ValueError('csrf_failed')
        return self._actor(row)

    def logout(self, token):
        self.db.execute('DELETE FROM platform_session WHERE token_hash=:token', {'token':digest(token)})

    def actor_by_id(self, ident):
        row = self.db.execute('SELECT id,username,role,can_download,can_manage_media FROM platform_user WHERE id=:id AND enabled=1',
                              {'id':ident}).mappings().first()
        if not row:
            raise ValueError('authentication_required')
        return self._actor(row)

    def create_api_token(self, actor, name):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise ValueError('invalid_token_name')
        from media_mcp.platform.limits import Budget
        Budget(self.db,self.clock).charge(actor.id,'token')
        token, ident = secrets.token_urlsafe(40), uuid.uuid4().hex
        now = self.clock()
        with self.db.begin() as conn:
            row = conn.execute(text('SELECT enabled,auth_version FROM platform_user WHERE id=:id'),
                               {'id':actor.id}).mappings().first()
            if not row or not row['enabled']:
                raise ValueError('authentication_required')
            active = conn.execute(text('''SELECT COUNT(*) FROM platform_api_token
                WHERE user_id=:user AND expires_at>:now AND auth_version=:version'''),
                {'user':actor.id,'now':now,'version':row['auth_version']}).scalar()
            if active >= 10:
                raise ValueError('account_token_limit')
            conn.execute(text('''INSERT INTO platform_api_token
                (id,token_hash,user_id,auth_version,name,expires_at,created_at)
                VALUES(:id,:hash,:user,:version,:name,:expiry,:now)'''),
                {'id':ident, 'hash':digest(token), 'user':actor.id, 'version':row['auth_version'],
                 'name':name.strip(), 'expiry':now+30*86400, 'now':now})
            self._event(conn, actor, 'mcp_token_created', 'token', ident)
        return {'id':ident, 'token':token, 'name':name.strip(), 'expires_at':now+30*86400}

    def verify_api_token(self, token):
        row = self.db.execute('''SELECT u.id,u.username,u.role,u.can_download,u.can_manage_media,t.expires_at FROM platform_api_token t
            JOIN platform_user u ON t.user_id=u.id WHERE t.token_hash=:hash AND t.expires_at>:now
            AND t.auth_version=u.auth_version AND u.enabled=1''',
            {'hash':digest(token), 'now':self.clock()}).mappings().first()
        if not row:
            raise ValueError('authentication_required')
        return self._actor(row), int(row['expires_at'])

    def api_tokens(self, actor):
        return [dict(row) for row in self.db.execute('''SELECT t.id,t.name,t.expires_at,t.created_at
            FROM platform_api_token t JOIN platform_user u ON u.id=t.user_id
            WHERE t.user_id=:user AND t.expires_at>:now AND t.auth_version=u.auth_version
            AND u.enabled=1 ORDER BY t.created_at''',
            {'user':actor.id, 'now':self.clock()}).mappings()]

    def revoke_api_token(self, actor, ident):
        with self.db.begin() as conn:
            conn.execute(text('DELETE FROM platform_api_token WHERE id=:id AND user_id=:user'),
                         {'id':ident, 'user':actor.id})
            self._event(conn, actor, 'mcp_token_revoked', 'token', ident)

    def users(self, actor):
        self.require_admin(actor)
        return [dict(row) for row in self.db.execute(
            'SELECT id,username,role,enabled,can_download,can_manage_media,created_at FROM platform_user ORDER BY created_at,id').mappings()]

    @staticmethod
    def require_admin(actor):
        if not actor.admin:
            raise ValueError('permission_denied')

    def create_user(self, actor, username, password, role='user', can_download=True, can_manage_media=False):
        self.require_admin(actor)
        username = self.validate_username(username)
        if role not in ('admin', 'user'):
            raise ValueError('invalid_role')
        if type(can_download) is not bool or type(can_manage_media) is not bool:
            raise ValueError('invalid_user_permissions')
        saved = password_hash(password)
        ident = uuid.uuid4().hex
        with self.db.begin() as conn:
            if conn.execute(text('SELECT id FROM platform_user WHERE username=:name'), {'name':username}).first():
                raise ValueError('username_exists')
            conn.execute(text('''INSERT INTO platform_user(id,username,password_hash,role,created_at,can_download,can_manage_media)
                VALUES(:id,:name,:password,:role,:now,:download,:manage)'''),
                {'id':ident, 'name':username, 'password':saved, 'role':role, 'now':self.clock(),
                 'download':int(can_download), 'manage':int(can_manage_media)})
            self._event(conn, actor, 'user_created', 'user', ident)
        return {'id':ident, 'username':username, 'role':role, 'enabled':True,
                'can_download':can_download or role == 'admin', 'can_manage_media':can_manage_media or role == 'admin'}

    def update_user(self, actor, ident, *, enabled, role, can_download=None, can_manage_media=None):
        self.require_admin(actor)
        if role not in ('admin', 'user') or type(enabled) is not bool:
            raise ValueError('invalid_user_update')
        if any(value is not None and type(value) is not bool for value in (can_download,can_manage_media)):
            raise ValueError('invalid_user_permissions')
        with self.db.begin() as conn:
            current = conn.execute(text('SELECT * FROM platform_user WHERE id=:id'), {'id':ident}).mappings().first()
            if not current:
                raise ValueError('user_not_found')
            if current['role'] == 'admin' and current['enabled'] and (not enabled or role != 'admin'):
                count = conn.execute(text("SELECT COUNT(*) FROM platform_user WHERE role='admin' AND enabled=1")).scalar()
                if count <= 1:
                    raise ValueError('last_admin_required')
            conn.execute(text('''UPDATE platform_user SET enabled=:enabled,role=:role,
                can_download=:download,can_manage_media=:manage,auth_version=auth_version+1 WHERE id=:id'''),
                {'id':ident, 'enabled':int(enabled), 'role':role,
                 'download':current['can_download'] if can_download is None else int(can_download),
                 'manage':current['can_manage_media'] if can_manage_media is None else int(can_manage_media)})
            conn.execute(text('DELETE FROM platform_session WHERE user_id=:id'), {'id':ident})
            self._event(conn, actor, 'user_updated', 'user', ident)

    def change_password(self, actor, old_password, new_password):
        row = self.db.execute('SELECT password_hash FROM platform_user WHERE id=:id',
                              {'id':actor.id}).mappings().first()
        if not row or not verify_password(old_password, row['password_hash']):
            raise ValueError('invalid_credentials')
        saved = password_hash(new_password)
        with self.db.begin() as conn:
            changed = conn.execute(text('''UPDATE platform_user SET password_hash=:password,
                auth_version=auth_version+1 WHERE id=:id AND password_hash=:old'''),
                {'id':actor.id, 'password':saved, 'old':row['password_hash']}).rowcount
            if changed != 1:
                raise ValueError('credentials_changed_retry_login')
            conn.execute(text('DELETE FROM platform_session WHERE user_id=:id'), {'id':actor.id})
            self._event(conn, actor, 'password_changed', 'user', actor.id)

    def allowed(self, actor, kind, object_id, *, manage=False):
        if actor.admin or (kind == 'media' and actor.can_manage_media):
            return True
        row = self.db.execute('''SELECT permission FROM platform_access
            WHERE kind=:kind AND object_id=:object AND user_id=:user''',
            {'kind':kind, 'object':str(object_id), 'user':actor.id}).first()
        return bool(row and (not manage or row[0] == 'manage'))

    def grant(self, actor, kind, object_id, user_id, permission):
        self.require_admin(actor)
        if kind not in ('task', 'media') or permission not in ('read', 'manage', 'none'):
            raise ValueError('invalid_grant')
        with self.db.begin() as conn:
            if not conn.execute(text('SELECT id FROM platform_user WHERE id=:id'), {'id':user_id}).first():
                raise ValueError('user_not_found')
            table = 'media_mcp_record' if kind == 'task' else 'media_link'
            suffix = " AND kind='acquisition'" if kind == 'task' else ''
            if not conn.execute(text(f'SELECT id FROM {table} WHERE id=:id{suffix}'), {'id':object_id}).first():
                raise ValueError('object_not_found')
            if permission == 'none':
                conn.execute(text('DELETE FROM platform_access WHERE kind=:kind AND object_id=:object AND user_id=:user'),
                             {'kind':kind, 'object':str(object_id), 'user':user_id})
            else:
                conn.execute(text('''INSERT INTO platform_access(kind,object_id,user_id,permission)
                    VALUES(:kind,:object,:user,:permission) ON CONFLICT(kind,object_id,user_id)
                    DO UPDATE SET permission=excluded.permission'''),
                    {'kind':kind, 'object':str(object_id), 'user':user_id, 'permission':permission})
            self._event(conn, actor, 'allocation_'+permission, kind, str(object_id), user_id)

    def events(self, actor, after=0, limit=50):
        limit = min(max(int(limit), 1), 100)
        query = '''SELECT * FROM platform_event WHERE id>:after
            AND (:admin=1 OR actor_id=:user OR subject_id=:user) ORDER BY id LIMIT :limit'''
        return [dict(row) for row in self.db.execute(query, {
            'after':int(after), 'admin':int(actor.admin), 'user':actor.id, 'limit':limit}).mappings()]

    def event(self, actor, action, kind, object_id):
        with self.db.begin() as conn:
            self._event(conn, actor, action, kind, object_id)

    def _event(self, conn, actor, action, kind, object_id, subject_id=None):
        conn.execute(text('''INSERT INTO platform_event(actor_id,action,kind,object_id,subject_id,created_at)
            VALUES(:actor,:action,:kind,:object,:subject,:now)'''),
            {'actor':actor.id, 'action':action, 'kind':kind, 'object':object_id,
             'subject':subject_id, 'now':self.clock()})
