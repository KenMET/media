"""One persistent Media model policy, shared by control API and worker processes."""
import re
from sqlalchemy import text
from media_mcp.storage.client import DatabaseClient

DEFAULT_MODEL = 'gpt-6.1-terra'
DEFAULT_EFFORT = 'low'


def validate_policy(model, effort):
    if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,99}', model):
        raise ValueError('invalid_model')
    if effort not in {'low', 'medium'}:
        raise ValueError('invalid_reasoning_effort')


class ModelSettings:
    def __init__(self, database=None):
        self.db = database or DatabaseClient()
        self.db.execute('''CREATE TABLE IF NOT EXISTS media_model_settings (
            id INTEGER PRIMARY KEY CHECK(id=1), model TEXT NOT NULL,
            effort TEXT NOT NULL, revision INTEGER NOT NULL,
            updated_by TEXT NOT NULL, updated_at TEXT NOT NULL)''')

    def get(self):
        row = self.db.execute('SELECT model,effort,revision,updated_at FROM media_model_settings WHERE id=1').mappings().first()
        policy = dict(row) if row else {'model':DEFAULT_MODEL, 'effort':DEFAULT_EFFORT,
                                       'revision':0, 'updated_at':None}
        validate_policy(policy['model'], policy['effort'])
        return policy

    def save(self, *, model, effort, revision, actor, accounts):
        if not actor.admin:
            raise ValueError('permission_denied')
        validate_policy(model, effort)
        with self.db.begin() as conn:
            row = conn.execute(text('SELECT revision FROM media_model_settings WHERE id=1')).first()
            if (row[0] if row else 0) != revision:
                raise ValueError('model_settings_changed')
            conn.execute(text('''INSERT INTO media_model_settings VALUES
                (1,:model,:effort,:revision,:actor,CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET model=excluded.model,effort=excluded.effort,
                  revision=excluded.revision,updated_by=excluded.updated_by,updated_at=excluded.updated_at'''),
                {'model':model, 'effort':effort, 'revision':revision+1, 'actor':actor.id})
            accounts._event(conn, actor, 'model_settings_updated', 'model_settings', str(revision+1))
        return self.get()


def load_model_settings():
    return ModelSettings().get()


def available_models():
    # Listing models does not submit a model turn or inherit server defaults.
    from media_mcp.ingest.clients.codex import CodexMediaClient
    client = CodexMediaClient(timeout=15, max_retries=0)
    data = client._control('model/list', {'limit':100})
    output = []
    for item in data.get('data', []):
        model = item.get('model') or item.get('id')
        efforts = [x.get('reasoningEffort') for x in item.get('supportedReasoningEfforts', [])
                   if x.get('reasoningEffort') in {'low','medium'}]
        if efforts:
            validate_policy(model, efforts[0])
            output.append({'model':model, 'efforts':efforts})
    # Never certify a model absent from this bounded listing.
    return output
