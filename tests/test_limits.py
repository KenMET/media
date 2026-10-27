import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from concurrent.futures import ThreadPoolExecutor

from media_mcp.platform.accounts import Accounts
from media_mcp.platform.limits import Budget
from media_mcp.platform.service import PlatformService
from media_mcp.storage.client import DatabaseClient
from media_mcp.storage.records import Records
from test_acquire import data


class LimitsTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        env=patch.dict(os.environ,{'MEDIA_DB_PATH':str(Path(directory.name)/'state/db.sqlite3')})
        env.start()
        self.addCleanup(env.stop)
        self.db=DatabaseClient()
        self.now=1000
        self.budget=Budget(self.db,lambda:self.now)

    def test_rate_is_shared_across_instances_separates_users_and_expires(self):
        other=Budget(DatabaseClient(),lambda:self.now)
        for _ in range(30):
            other.charge('alice','search')
        with self.assertRaisesRegex(ValueError,'account_rate_limited'):
            self.budget.charge('alice','search')
        self.budget.charge('bob','search')
        self.now+=60
        self.budget.charge('alice','search')

    def test_concurrency_is_shared_and_exception_releases_slot(self):
        other=Budget(DatabaseClient(),lambda:self.now)
        with self.budget.operation('alice','search'):
            with other.operation('alice','search'):
                with self.assertRaisesRegex(ValueError,'account_concurrency_limited'):
                    with self.budget.operation('alice','search'):
                        self.fail('must not enter')
                with self.budget.operation('bob','search'):
                    pass
        with self.assertRaisesRegex(RuntimeError,'operation_failed'):
            with other.operation('alice','search'):
                raise RuntimeError('operation_failed')
        with self.budget.operation('alice','search'):
            pass

    def test_last_rate_slot_is_atomic_between_competing_requests(self):
        for _ in range(29):
            self.budget.charge('alice','search')
        def attempt(_):
            try:
                Budget(DatabaseClient(),lambda:self.now).charge('alice','search')
                return 'accepted'
            except ValueError as error:
                return str(error)
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertCountEqual(list(executor.map(attempt,range(2))),['accepted','account_rate_limited'])

    def test_global_queue_counts_unknown_legacy_tasks_but_not_completed(self):
        records=Records(self.db)
        records.initialize()
        for index in range(100):
            records.put('acquisition',{},'submission_unknown' if index==0 else 'queued')
        with self.assertRaisesRegex(ValueError,'account_queue_full'):
            self.budget.admit_job('new-user')
        row=records.list('acquisition',1)[0]
        records.update(row,'completed')
        self.budget.admit_job('new-user')

    def test_queue_limit_preserves_idempotent_unknown_submission_lookup(self):
        accounts=Accounts(self.db,clock=lambda:self.now)
        accounts.initialize()
        actor=accounts.bootstrap('owner','owner-password-123','x'*32,'x'*32)
        records=Records(self.db)
        records.initialize()
        service=PlatformService(actor,accounts,records,tmdb=Mock(),indexer=Mock())
        service.service.library=lambda _: {'media':[],'active_jobs':[]}
        plan=service.service.records.put('plan',data())
        first=service.start(plan['id'],1,'original-request')
        row=records.get(first['job_id'])
        records.update(row,'submission_unknown')
        for _ in range(9):
            records.put('acquisition',{'_platform_owner':actor.id},'needs_review')
        other=service.service.records.put('plan',data())
        with self.assertRaisesRegex(ValueError,'account_queue_full'):
            service.start(other['id'],1,'different-request')
        # Same key still returns the fenced task even while queue/rate budgets are full.
        for _ in range(9):
            self.budget.charge(actor.id,'submission')
        repeated=service.start(plan['id'],1,'original-request')
        self.assertEqual(repeated['job_id'],first['job_id'])
        self.assertEqual(repeated['stage'],'submission_unknown')
        self.assertEqual(len(records.list('acquisition',100)),10)

    def test_token_quantity_and_frequency_are_backend_enforced(self):
        accounts=Accounts(self.db,clock=lambda:self.now)
        accounts.initialize()
        actor=accounts.bootstrap('owner','owner-password-123','x'*32,'x'*32)
        for _ in range(5):
            accounts.create_api_token(actor,'fixture')
        with self.assertRaisesRegex(ValueError,'account_rate_limited'):
            accounts.create_api_token(actor,'over-budget')
        self.now+=3600
        for _ in range(5):
            accounts.create_api_token(actor,'fixture')
        self.now+=3600
        with self.assertRaisesRegex(ValueError,'account_token_limit'):
            accounts.create_api_token(actor,'over-count')
