"""Check the installed artifact rather than a PYTHONPATH source checkout."""
import importlib.metadata
import importlib.resources
import json

import media_mcp


if __name__ == '__main__':
    assert 'site-packages' in media_mcp.__file__
    assert importlib.metadata.version('media-mcp') == '0.3.0'
    scripts = {item.name for item in importlib.metadata.distribution('media-mcp').entry_points
               if item.group == 'console_scripts'}
    assert {'media-mcp','media-worker','media-web','media-gateway'} <= scripts
    assets = importlib.resources.files('media_mcp.platform')/'static'
    for name in ('index.html','app.css','app.js','i18n.js','ux.js'):
        assert (assets/name).is_file()
    print(json.dumps({'package':'media-mcp','version':'0.3.0','entrypoints':4,'web_assets':5,'verified':True}))
