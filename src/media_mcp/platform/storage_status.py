"""Read actual mounted media filesystem capacity without traversing media."""
import os
import shutil
from pathlib import Path


def storage_status():
    result=[]
    for role,name,default in [('downloads','MEDIA_DOWNLOAD_ROOT','/data/downloads'),
                              ('library','MEDIA_LIBRARY_ROOT','/data/media_hub')]:
        path=Path(os.environ.get(name,default))
        try:
            usage=shutil.disk_usage(path)
            result.append({'role':role,'path':str(path),'device':path.stat().st_dev,
                           'total':usage.total,'used':usage.used,'free':usage.free,'available':True})
        except OSError:
            result.append({'role':role,'available':False})
    return result
