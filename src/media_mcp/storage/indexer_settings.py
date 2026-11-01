"""Private local search preferences; Jackett remains owner of indexer configuration."""
import json
import os
from pathlib import Path
import tempfile

from media_mcp.storage.client import FileLock, database_path


class IndexerSettings:
    def __init__(self, path=None):
        self.path = Path(path) if path else database_path().parent/'jackett-indexers.json'

    def get(self):
        try:
            value = json.loads(self.path.read_text())
        except FileNotFoundError:
            return {'revision':0, 'disabled':[], 'tests':{}}
        except (OSError, ValueError):
            raise ValueError('jackett_preferences_unavailable') from None
        if not isinstance(value, dict) or type(value.get('revision')) is not int or not isinstance(value.get('disabled'), list) or not isinstance(value.get('tests'), dict):
            raise ValueError('jackett_preferences_unavailable')
        return value

    def update(self, change, revision=None):
        lock = FileLock(self.path.with_suffix('.lock'), timeout=5)
        try:
            lock.acquire()
            value = self.get()
            if revision is not None and value['revision'] != revision:
                raise ValueError('jackett_settings_changed')
            change(value)
            value['revision'] += 1
            with tempfile.NamedTemporaryFile(mode='w', dir=self.path.parent, prefix='.jackett-', delete=False) as output:
                temporary = Path(output.name)
                try:
                    os.chmod(temporary,0o600)
                    json.dump(value, output)
                    output.flush();os.fsync(output.fileno())
                    os.replace(temporary, self.path)
                finally:
                    temporary.unlink(missing_ok=True)
            return value
        finally:
            lock.close()
