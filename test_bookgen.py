#!/usr/bin/env python3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bookgen


class BookGenFlowTest(unittest.TestCase):
    def test_generates_chapters_for_xiaohongmao(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "story.txt"
            toc = tmp_path / "story-toc.txt"

            source.write_text("这是一本关于小红帽的故事背景。", encoding="utf-8")
            toc.write_text("# 第一章\n# 第二章\n", encoding="utf-8")

            responses = [
                "# 第一章\n小红帽走进森林。",
                "小红帽进入森林并遇到线索。",
                "# 第二章\n小红帽遇见了大灰狼。",
                "小红帽遇见大灰狼，冲突升级。",
            ]

            def fake_call_with_retries(cfg, messages, retries=3, echo=False):  # noqa: ANN001
                return responses.pop(0)

            with patch("bookgen.call_with_retries", side_effect=fake_call_with_retries):
                rc = bookgen.run(
                    [
                        str(source),
                        str(toc),
                        "-n",
                        "2",
                        "-c",
                        "小红帽 第%d章",
                        "-l",
                        "Chinese",
                    ]
                )

            self.assertEqual(rc, 0)
            outdir = tmp_path / "story"

            chapter_01 = (outdir / "chapter_01.md").read_text(encoding="utf-8")
            chapter_02 = (outdir / "chapter_02.md").read_text(encoding="utf-8")
            full_book = (outdir / "full_book.md").read_text(encoding="utf-8")

            self.assertIn("小红帽", chapter_01)
            self.assertIn("小红帽", chapter_02)
            self.assertIn("小红帽", full_book)
            self.assertTrue((outdir / "chapter_01_summary.txt").exists())
            self.assertTrue((outdir / "chapter_02_summary.txt").exists())


if __name__ == "__main__":
    unittest.main()
