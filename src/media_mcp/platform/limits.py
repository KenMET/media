"""Cross-process account budgets. OS locks release even when a process dies."""
from contextlib import contextmanager
from functools import wraps
import hashlib
import time

from sqlalchemy import text

from media_mcp.storage.client import FileLock


# Count, window seconds, concurrent expensive calls. Independent of browser UI.
POLICIES = {'search':(30,60,2), 'plan':(10,60,2), 'submission':(10,600,2),
            'token':(5,3600,1)}


class Budget:
    def __init__(self, db, clock=time.time):
        self.db, self.clock = db, clock
        db.execute('''CREATE TABLE IF NOT EXISTS platform_budget (
            key TEXT PRIMARY KEY, used INTEGER NOT NULL, reset_at REAL NOT NULL)''')

    def charge(self, user, operation):
        count, window, _ = POLICIES[operation]
        key = hashlib.sha256((user+':'+operation).encode()).hexdigest()
        now = self.clock()
        with self.db.begin() as conn:
            conn.execute(text('DELETE FROM platform_budget WHERE reset_at<=:now'), {'now':now})
            row = conn.execute(text('SELECT used FROM platform_budget WHERE key=:key'), {'key':key}).first()
            if row and row[0] >= count:
                raise ValueError('account_rate_limited')
            conn.execute(text('''INSERT INTO platform_budget(key,used,reset_at) VALUES(:key,1,:reset)
                ON CONFLICT(key) DO UPDATE SET used=used+1'''), {'key':key,'reset':now+window})

    @contextmanager
    def operation(self, user, operation):
        held = None
        for slot in range(POLICIES[operation][2]):
            key = hashlib.sha256((str(self.db.path)+':budget:'+user+':'+operation+':'+str(slot)).encode()).hexdigest()
            lock = FileLock(self.db.path.parent/'locks'/(key+'.lock'))
            try:
                lock.acquire()
            except RuntimeError as error:
                lock.close()
                if str(error) != 'media_busy_retry_later':
                    raise
            else:
                held = lock
                break
        if held is None:
            raise ValueError('account_concurrency_limited')
        try:
            self.charge(user, operation)
            yield
        finally:
            held.close()

    def call(self, user, operation, function, *args, **kwargs):
        with self.operation(user, operation):
            return function(*args, **kwargs)

    def admit_job(self, user):
        # Caller holds the existing global media mutation lock through insertion.
        rows = self.db.execute('''SELECT json_extract(data,'$._platform_owner') AS owner,
            COUNT(*) AS total FROM media_mcp_record WHERE kind='acquisition'
            AND state NOT IN ('completed','completed_with_warnings','failed','cancelled')
            GROUP BY json_extract(data,'$._platform_owner')''').mappings().all()
        if sum(row['total'] for row in rows) >= 100 or sum(
                row['total'] for row in rows if row['owner'] == user) >= 10:
            raise ValueError('account_queue_full')
        self.charge(user, 'submission')


def limited(operation):
    def decorate(function):
        @wraps(function)
        def invoke(self, *args, **kwargs):
            return Budget(self.accounts.db,self.accounts.clock).call(
                self.actor.id,operation,function,self,*args,**kwargs)
        return invoke
    return decorate
