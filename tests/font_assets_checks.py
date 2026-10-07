"""Offline font integrity and privacy checks. Never fetch upstream during tests."""
import hashlib
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'app/static/fonts'


class FontAssetsTests(unittest.TestCase):
    def test_manifest_and_woff2_integrity(self):
        manifest = json.loads((ROOT / 'manifest.json').read_text())
        self.assertEqual(len(manifest['assets']), 107)
        for asset in manifest['assets']:
            data = (ROOT / asset['file']).read_bytes()
            self.assertEqual(data[:4], b'wOF2')
            self.assertEqual(hashlib.sha256(data).hexdigest(), asset['sha256'])
            self.assertTrue(asset['url'].startswith('https://fonts.gstatic.com/'))

    def test_font_faces_have_only_local_sources_and_separate_names(self):
        css = (ROOT / 'fonts.css').read_text()
        urls = re.findall(r'url\(([^)]+)\)', css)
        self.assertEqual(len(urls), 107)
        self.assertTrue(all(url.startswith('/static/fonts/') and (ROOT / url.split('/')[-1]).is_file() for url in urls))
        self.assertNotIn('https:', css)
        self.assertIn("'ChordLab Manrope'", css)
        self.assertIn("'ChordLab Noto TC'", css)
        self.assertNotIn("font-family: 'Noto Sans TC'", css)
        self.assertEqual(css.count('font-display: swap'), 107)

    def test_license_notices_retained(self):
        for name in ('OFL-Manrope.txt', 'OFL-NotoSansTC.txt'):
            notice = (ROOT / name).read_text()
            self.assertIn('SIL OPEN FONT LICENSE', notice)
            self.assertIn('Copyright', notice)


if __name__ == '__main__':
    unittest.main()
