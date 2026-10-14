#!/usr/bin/env python3
"""Pack a port's build outputs as a release asset, and unpack one into a build root.

A port describes its release in a JSON spec:
  asset       archive file name, e.g. "openal-orbis.tar.xz"
  outputs     output directories under the build root. Each keeps its top-level files
              (modules, audits, symbol lists) and, under sources/, only licence files and
              the extra names in source_files. Object files, CMake trees and stamps stay out.
              The unstripped ELF behind each signed module goes to a separate
              <asset>-debug.tar.xz, as AngelAuraMC publishes its debug info apart from its JREs.
  files       further paths or globs under the build root, kept whole (.git excluded).

The archive carries release-inventory.json: the SHA-256 and mode of every file. Unpacking
checks the archive against an expected SHA-256, checks every file against the inventory, and
refuses to replace existing files.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import tarfile
import tempfile

INVENTORY = 'release-inventory.json'
LICENCE = re.compile(r'^(licen[cs]e|copying|licensing|notice|ftl)(\..*)?$|_licen[cs]e\.txt$', re.IGNORECASE)
SKIPPED_SUFFIXES = ('.o', '.oelf')


def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def relative(name):
    path = Path(name)
    if path.is_absolute() or '..' in path.parts or not path.parts:
        raise ValueError('Unsafe release path: ' + name)
    return path


def regular(path, root):
    """A file to pack. A link is packed as a copy of its target, which must be inside the root."""
    target = path.resolve()
    if not target.is_file() or Path(root).resolve() not in target.parents:
        raise ValueError('Release inputs must be files inside the build root: ' + str(path))
    return path


def is_elf(path):
    with path.open('rb') as source:
        return source.read(4) == b'\x7fELF'


def debug_asset(spec):
    asset = spec['asset']
    return asset.removesuffix('.tar.xz') + '-debug.tar.xz'


def selected(root, spec, debug=False):
    """The files the spec selects as paths relative to root: the release, or with debug its unstripped ELFs."""
    root = Path(root)
    chosen = set()
    extra = set(spec.get('source_files', ()))
    for name in spec.get('outputs', ()):
        output = root / relative(name)
        if not output.is_dir():
            raise ValueError('Missing release output: ' + str(output))
        for path in sorted(output.iterdir()):
            if path.is_file() and not path.name.startswith('.') and path.suffix not in SKIPPED_SUFFIXES:
                if (path.suffix == '.so' and is_elf(path)) == debug:
                    chosen.add(regular(path, root).relative_to(root))
        if debug:
            continue
        sources = output / 'sources'
        if sources.is_dir():
            for path in sources.rglob('*'):
                if path.is_file() and (LICENCE.search(path.name) or path.name in extra):
                    chosen.add(regular(path, root).relative_to(root))
    for pattern in () if debug else spec.get('files', ()):
        relative(pattern)
        matches = sorted(root.glob(pattern))
        if not matches:
            raise ValueError('Release file pattern matched nothing: ' + pattern)
        for match in matches:
            for path in ([match] if match.is_file() else sorted(match.rglob('*'))):
                if path.is_file() and '.git' not in path.relative_to(root).parts:
                    chosen.add(regular(path, root).relative_to(root))
    if not chosen and not debug:
        raise ValueError('Release selects no files')
    return sorted(chosen)


def normalized(info):
    info.uid = info.gid = 0
    info.uname = info.gname = ''
    info.mtime = 0
    return info


def pack(root, spec, archive, debug=False):
    root, archive = Path(root).resolve(), Path(archive)
    files = selected(root, spec, debug)
    if not files:
        return None
    inventory = {'schema': 1, 'asset': archive.name,
                 'files': {path.as_posix(): {'sha256': digest(root / path),
                                             'mode': (root / path).stat().st_mode & 0o755}
                           for path in files}}
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        raise ValueError('Release asset already exists: ' + str(archive))
    with tarfile.open(archive, 'w:xz', preset=9) as target:
        data = (json.dumps(inventory, indent=2) + '\n').encode()
        info = normalized(tarfile.TarInfo(INVENTORY))
        info.size, info.mode = len(data), 0o644
        target.addfile(info, io.BytesIO(data))
        for path in files:
            source = (root / path).resolve()
            info = normalized(target.gettarinfo(source, arcname=path.as_posix()))
            with source.open('rb') as data:
                target.addfile(info, data)
    print(f'{archive}: {len(files)} files')
    return archive


def unpack(archive, root, expected):
    archive, root = Path(archive), Path(root)
    if digest(archive) != expected:
        raise ValueError('Release asset hash mismatch: ' + str(archive))
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.release-', dir=root) as directory:
        stage = Path(directory)
        with tarfile.open(archive, 'r:xz') as source:
            names = set()
            for member in source.getmembers():
                relative(member.name)
                if not member.isfile() or member.name in names:
                    raise ValueError('Unsafe release member: ' + member.name)
                names.add(member.name)
            source.extractall(stage, filter='data')
        report = json.loads((stage / INVENTORY).read_text())
        (stage / INVENTORY).unlink()
        actual = {path.relative_to(stage).as_posix(): {'sha256': digest(path), 'mode': path.stat().st_mode & 0o777}
                  for path in stage.rglob('*') if path.is_file()}
        if report.get('schema') != 1 or actual != report['files']:
            raise ValueError('Release inventory mismatch: ' + str(archive))
        for name in report['files']:
            if (root / name).exists():
                raise ValueError('Preserve existing output before unpacking: ' + str(root / name))
        for name in sorted(report['files']):
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(stage / name, target)
    print(f'{archive}: {len(report["files"])} files into {root}')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    packing = commands.add_parser('pack', help='archive the outputs a release spec selects')
    packing.add_argument('--root', type=Path, required=True, help='build root holding the outputs')
    packing.add_argument('--spec', type=Path, required=True)
    packing.add_argument('--dist', type=Path, required=True, help='directory for the asset')
    unpacking = commands.add_parser('unpack', help='check and extract a release asset into a build root')
    unpacking.add_argument('--archive', type=Path, required=True)
    unpacking.add_argument('--root', type=Path, required=True)
    unpacking.add_argument('--sha256', required=True)
    args = parser.parse_args()
    if args.command == 'pack':
        spec = json.loads(args.spec.read_text())
        pack(args.root, spec, args.dist / spec['asset'])
        pack(args.root, spec, args.dist / debug_asset(spec), debug=True)
    else:
        unpack(args.archive, args.root, args.sha256)


if __name__ == '__main__':
    main()
