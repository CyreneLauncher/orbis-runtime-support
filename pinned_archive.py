"""Download, verify and unpack a hash-pinned upstream source archive.

An entry is one lock record with url, filename and sha256. Each port keeps its own
pins and passes the record in; this module holds no pins itself.
"""
import hashlib
import shutil
import tarfile
import urllib.request
from pathlib import Path


def archive(entry, downloads, fetch=False):
    """Returns the verified archive for entry, downloading it only when fetch is set."""
    path = Path(downloads) / entry['filename']
    if not path.is_file():
        if not fetch:
            raise SystemExit(f'missing {path}; download {entry["url"]} or pass --fetch')
        path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(entry['url']) as response, path.open('wb') as target:
            shutil.copyfileobj(response, target)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != entry['sha256']:
        raise SystemExit(f'{path} SHA-256 {digest} is not the pinned {entry["sha256"]}')
    return path


def extract(path, destination):
    """Fresh extraction; returns the archive's single top-level directory."""
    destination = Path(destination)
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    with tarfile.open(path) as tar:
        tar.extractall(destination, filter='data')
    (top,) = destination.iterdir()
    return top
