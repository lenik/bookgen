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

            def fake_call_with_retries(cfg, messages, retries=3, echo=False, think_enabled=None):  # noqa: ANN001
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

    def test_full_book_removes_think_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            outdir = tmp_path / "out"
            outdir.mkdir(parents=True, exist_ok=True)

            ch1 = outdir / "chapter_01.md"
            ch2 = outdir / "chapter_02.md"
            ch1.write_text("# 第1章\n内容A\n<think>internal\nreasoning</think>\n结尾A\n", encoding="utf-8")
            ch2.write_text("# 第2章\n<think>secret</think>\n内容B\n", encoding="utf-8")

            full_path = bookgen.build_full_book(outdir, [ch1, ch2])
            full_text = full_path.read_text(encoding="utf-8")

            self.assertIn("内容A", full_text)
            self.assertIn("内容B", full_text)
            self.assertNotIn("<think>", full_text)
            self.assertNotIn("</think>", full_text)

    def test_summary_strips_think_and_bridge_uses_clean_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "story.txt"
            toc = tmp_path / "story-toc.txt"

            source.write_text("背景。", encoding="utf-8")
            toc.write_text("# 第一章\n# 第二章\n", encoding="utf-8")

            responses = [
                "# 第一章\n正文一。",
                "<think>hidden</think>干净摘要一",
                "# 第二章\n正文二。",
                "<think>hidden2</think>干净摘要二",
            ]
            call_idx = {"n": 0}

            def fake_call_with_retries(cfg, messages, retries=3, echo=False, think_enabled=None):  # noqa: ANN001
                call_idx["n"] += 1
                # 3rd call is chapter 2 generation; bridge should already be cleaned.
                if call_idx["n"] == 3:
                    bridge_user_prompt = messages[1]["content"]
                    self.assertIn("干净摘要一", bridge_user_prompt)
                    self.assertNotIn("<think>", bridge_user_prompt)
                return responses.pop(0)

            with patch("bookgen.call_with_retries", side_effect=fake_call_with_retries):
                rc = bookgen.run([str(source), str(toc), "-n", "2", "-l", "Chinese"])

            self.assertEqual(rc, 0)
            outdir = tmp_path / "story"
            s1 = (outdir / "chapter_01_summary.txt").read_text(encoding="utf-8")
            s2 = (outdir / "chapter_02_summary.txt").read_text(encoding="utf-8")
            self.assertIn("干净摘要一", s1)
            self.assertIn("干净摘要二", s2)
            self.assertNotIn("<think>", s1)
            self.assertNotIn("<think>", s2)

    def test_fast_mode_strips_think_from_chapter_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "story.txt"
            toc = tmp_path / "story-toc.txt"

            source.write_text("背景。", encoding="utf-8")
            toc.write_text("# 第一章\n", encoding="utf-8")

            responses = [
                "# 第一章\n<think>hidden-chapter</think>\n正文",
                "<think>hidden-summary</think>摘要",
            ]

            def fake_call_with_retries(cfg, messages, retries=3, echo=False, think_enabled=None):  # noqa: ANN001
                return responses.pop(0)

            with patch("bookgen.call_with_retries", side_effect=fake_call_with_retries):
                rc = bookgen.run([str(source), str(toc), "-n", "1", "-l", "Chinese", "-f"])

            self.assertEqual(rc, 0)
            outdir = tmp_path / "story"
            chapter = (outdir / "chapter_01.md").read_text(encoding="utf-8")
            summary = (outdir / "chapter_01_summary.txt").read_text(encoding="utf-8")
            self.assertIn("正文", chapter)
            self.assertIn("摘要", summary)
            self.assertNotIn("<think>", chapter)
            self.assertNotIn("<think>", summary)

    def test_summary_forces_think_off_and_generation_restores_on(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "story.txt"
            toc = tmp_path / "story-toc.txt"
            source.write_text("背景。", encoding="utf-8")
            toc.write_text("# 第一章\n# 第二章\n", encoding="utf-8")

            responses = ["正文1", "摘要1", "正文2", "摘要2"]
            think_modes = []

            def fake_call_with_retries(cfg, messages, retries=3, echo=False, think_enabled=None):  # noqa: ANN001
                think_modes.append(think_enabled)
                return responses.pop(0)

            with patch("bookgen.call_with_retries", side_effect=fake_call_with_retries):
                rc = bookgen.run([str(source), str(toc), "-n", "2", "-l", "Chinese"])

            self.assertEqual(rc, 0)
            self.assertEqual(think_modes, [True, False, True, False])

    def test_echo_mode_also_echoes_summary_stream(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "story.txt"
            toc = tmp_path / "story-toc.txt"
            source.write_text("背景。", encoding="utf-8")
            toc.write_text("# 第一章\n", encoding="utf-8")

            responses = ["正文", "摘要"]
            echo_flags = []

            def fake_call_with_retries(cfg, messages, retries=3, echo=False, think_enabled=None):  # noqa: ANN001
                echo_flags.append(echo)
                return responses.pop(0)

            with patch("bookgen.call_with_retries", side_effect=fake_call_with_retries):
                rc = bookgen.run([str(source), str(toc), "-n", "1", "-l", "Chinese", "--echo"])

            self.assertEqual(rc, 0)
            self.assertEqual(echo_flags, [True, True])


if __name__ == "__main__":
    unittest.main()
