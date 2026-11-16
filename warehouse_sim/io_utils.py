"""Atomic local artifacts and an OS-held lock for resumable jobs."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as file:
        for chunk in iter(lambda:file.read(1024*1024),b''):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.'+path.name+'-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as file:
            json.dump(value,file,indent=2,allow_nan=False)
            file.write('\n')
            file.flush()
            os.fsync(file.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def job_lock(directory):
    directory = Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    with (directory/'run.lock').open('a+') as file:
        try:
            fcntl.flock(file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('Another process is using this output directory') from exc
        try:
            yield
        finally:
            fcntl.flock(file,fcntl.LOCK_UN)
