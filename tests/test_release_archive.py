import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('release_archive', Path(__file__).parents[1] / 'release_archive.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def write(path, data=b'x', mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(mode)


class ReleaseArchiveTests(unittest.TestCase):
    def layout(self, root):
        write(root / 'out/libfoo.prx', b'prx', 0o755)
        write(root / 'out/libfoo.so', b'\x7fELF unstripped', 0o755)
        write(root / 'out/foo-audit.json', b'{}')
        write(root / 'out/foo.o')
        write(root / 'out/.foo.inputs.sha256')
        write(root / 'out/obj/bar.o')
        write(root / 'out/sources/foo-1.0/COPYING', b'licence')
        write(root / 'out/sources/foo-1.0/src/foo.c')
        write(root / 'out/sources/foo-1.0/mod/zstd_license.txt')
        write(root / 'out/sources/foo-1.0/keep.h')
        write(root / 'shared/include/a.h')
        write(root / 'shared/.git/HEAD')
        return {'asset': 'foo.tar.xz', 'outputs': ['out'], 'source_files': ['keep.h'], 'files': ['shared']}

    def test_selects_outputs_licences_and_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            chosen = {p.as_posix() for p in release.selected(root, self.layout(root))}
            self.assertEqual(chosen, {'out/libfoo.prx', 'out/foo-audit.json', 'out/sources/foo-1.0/COPYING',
                                      'out/sources/foo-1.0/mod/zstd_license.txt', 'out/sources/foo-1.0/keep.h',
                                      'shared/include/a.h'})
            debug = {p.as_posix() for p in release.selected(root, self.layout(root), debug=True)}
            self.assertEqual(debug, {'out/libfoo.so'})

    def test_debug_asset_carries_only_the_unstripped_elf(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            spec = self.layout(root / 'build')
            self.assertEqual(release.debug_asset(spec), 'foo-debug.tar.xz')
            archive = release.pack(root / 'build', spec, root / 'dist' / release.debug_asset(spec), debug=True)
            release.unpack(archive, root / 'target', release.digest(archive))
            self.assertEqual(sorted(p.name for p in (root / 'target').rglob('*') if p.is_file()), ['libfoo.so'])
            self.assertIsNone(release.pack(root / 'build', {'asset': 'x.tar.xz', 'files': ['shared']},
                                           root / 'dist/x-debug.tar.xz', debug=True))

    def test_roundtrip_keeps_content_and_mode_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            archive = release.pack(root / 'build', self.layout(root / 'build'), root / 'dist/foo.tar.xz')
            sha = release.digest(archive)
            release.unpack(archive, root / 'target', sha)
            self.assertEqual((root / 'target/out/libfoo.prx').read_bytes(), b'prx')
            self.assertEqual((root / 'target/out/libfoo.prx').stat().st_mode & 0o777, 0o755)
            with self.assertRaises(ValueError):
                release.unpack(archive, root / 'target', sha)
            with self.assertRaises(ValueError):
                release.unpack(archive, root / 'other', '0' * 64)

    def test_links_inside_root_are_copied_and_outside_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write(root / 'build/shared/real.h', b'header')
            (root / 'build/shared/link.h').symlink_to('real.h')
            archive = release.pack(root / 'build', {'asset': 'a.tar.xz', 'files': ['shared']}, root / 'dist/a.tar.xz')
            release.unpack(archive, root / 'target', release.digest(archive))
            self.assertFalse((root / 'target/shared/link.h').is_symlink())
            self.assertEqual((root / 'target/shared/link.h').read_bytes(), b'header')
            write(root / 'outside.h')
            (root / 'build/shared/escape.h').symlink_to(root / 'outside.h')
            with self.assertRaises(ValueError):
                release.selected(root / 'build', {'files': ['shared']})

    def test_rejects_traversal_and_inventory_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name, inventory in (('../escape', {}), ('out/file', {'out/file': {'sha256': '0' * 64, 'mode': 0o644}})):
                archive = root / 'bad.tar.xz'
                with tarfile.open(archive, 'w:xz') as target:
                    for member, data in ((release.INVENTORY, json.dumps({'schema': 1, 'files': inventory}).encode()),
                                         (name, b'bad')):
                        info = tarfile.TarInfo(member)
                        info.size = len(data)
                        target.addfile(info, io.BytesIO(data))
                with self.assertRaises(ValueError):
                    release.unpack(archive, root / 'target', hashlib.sha256(archive.read_bytes()).hexdigest())
                self.assertFalse((root / 'escape').exists())
                self.assertFalse((root / 'target/out/file').exists())


if __name__ == '__main__':
    unittest.main()
