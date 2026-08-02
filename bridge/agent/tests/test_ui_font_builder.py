from __future__ import annotations

import unittest
from pathlib import Path

from tools.build_ui_font import OUTPUT_SHA256, PIXEL_SIZE, glyph_codepoints, sha256


class UiFontBuilderTests(unittest.TestCase):
    def test_gb2312_font_asset_is_complete_and_reproducible(self) -> None:
        codepoints = glyph_codepoints()
        self.assertEqual(len(codepoints), 7_543)
        for character in "回复问候社交平台任务完成":
            self.assertIn(ord(character), codepoints)

        self.assertEqual(PIXEL_SIZE, 13)
        asset = Path(
            f"firmware/m5stack-cardputer-adv/assets/fonts/"
            f"cardbridge-ui-{PIXEL_SIZE}.bff"
        )
        self.assertTrue(asset.is_file())
        self.assertEqual(sha256(asset), OUTPUT_SHA256)

        # BFF `head` stores the compression algorithm at byte 41. Keep this
        # zero: M5GFX 0.2.25 corrupts some compressed glyph bitmaps.
        self.assertEqual(asset.read_bytes()[41], 0)


if __name__ == "__main__":
    unittest.main()
