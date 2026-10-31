"""Keep authored non-web content English without changing multilingual media data."""
from pathlib import Path
import re
import unittest


class ProjectLanguageTests(unittest.TestCase):
    def test_non_web_source_and_guidance_have_no_unlocalized_cjk_copy(self):
        root = Path(__file__).resolve().parents[1]
        web = root / 'src/media_mcp/platform/static'
        files = [root / name for name in ('AGENTS.md', 'README.md', '.env.example', 'setup.sh')]
        for directory in ('src', 'tests', 'docs', 'skills'):
            files.extend(p for p in (root / directory).rglob('*')
                         if p.is_file() and p.suffix in ('.py', '.mjs', '.cjs', '.md', '.json', '.c4'))
        failures = []
        for file in files:
            if web in file.parents:
                continue
            for number, line in enumerate(file.read_text().splitlines(), 1):
                if re.search(r'[\u3400-\u9fff]', line):
                    failures.append(f'{file.relative_to(root)}:{number}')
        self.assertEqual(failures, [], 'Use English copy; encode required multilingual data literals explicitly.')
