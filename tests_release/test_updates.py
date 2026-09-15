import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from easysync import updates


def release_data():
    tag = 'v1.2.3'
    name = 'Easy-Sync-Setup-1.2.3-x64.exe'
    return {'tag_name': tag, 'assets': [{
        'name': name,
        'browser_download_url': f'https://github.com/{updates.REPOSITORY}/releases/download/{tag}/{name}',
        'digest': 'sha256:' + hashlib.sha256(b'installer').hexdigest(), 'size': 9}]}


class UpdateTests(unittest.TestCase):
    def test_new_stable_only(self):
        data = release_data()
        self.assertEqual(updates.parse_release(data, '1.2.2').version, '1.2.3')
        self.assertIsNone(updates.parse_release(data, '1.2.3'))
        self.assertIsNone(updates.parse_release(data, '2.0.0'))
        data['prerelease'] = True
        self.assertIsNone(updates.parse_release(data, '1.0.0'))

    def test_reject_untrusted_or_unverifiable_asset(self):
        for key, value in [('browser_download_url', 'https://example.com/installer.exe'),
                           ('digest', ''), ('size', 0), ('size', 999999999)]:
            data = release_data()
            data['assets'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                updates.parse_release(data, '1.0.0')

    def test_download_bytes_verified_and_corruption_removed(self):
        release = updates.parse_release(release_data(), '1.0.0')
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            with patch.object(updates, '_request', return_value=io.BytesIO(b'installer')):
                path = updates.download(release, cache)
            self.assertEqual(path.read_bytes(), b'installer')
            before = set(cache.iterdir())
            for content in (b'incorrect', b'truncated', b'installer-too-large'):
                with patch.object(updates, '_request', return_value=io.BytesIO(content)):
                    with self.assertRaises(ValueError):
                        updates.download(release, cache)
                self.assertEqual(set(cache.iterdir()), before)


if __name__ == '__main__':
    unittest.main()
