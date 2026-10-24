import ast
from pathlib import Path
import unittest


class Portability(unittest.TestCase):
    def test_runtime_has_no_legacy_imports(self):
        package=Path(__file__).resolve().parents[1]/'src/media_mcp'
        for path in package.rglob('*.py'):
            tree=ast.parse(path.read_text(),filename=str(path))
            for node in ast.walk(tree):
                names=([node.module] if isinstance(node,ast.ImportFrom) and node.module else
                       [item.name for item in node.names] if isinstance(node,ast.Import) else [])
                self.assertFalse(any(name=='apps' or name.startswith('apps.') for name in names),str(path))
