#!/usr/bin/env python3
"""Standard-library regression tests: python3 -m unittest discover -s tools."""
import copy
import importlib.util
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("brochure_build", Path(__file__).with_name("build.py"))
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class PagePlanTests(unittest.TestCase):
    def setUp(self):
        self.pages = build.load_pages()

    def fixture(self, count):
        pages = copy.deepcopy(self.pages)
        back, body = pages.pop()
        for n in range(16, count):
            pages.append(({"page": n, "layout": "standard", "source": "test fixture"},
                          f"Future test page {n}."))
        back["page"] = count
        pages.append((back, body))
        return pages

    def test_default_is_twenty_with_four_blanks(self):
        original = copy.deepcopy(self.pages)
        planned = build.plan_pages(self.pages)
        self.assertEqual(len(planned), 20)
        self.assertEqual([m["page"] for m, _ in planned], list(range(1, 21)))
        self.assertEqual([m["page"] for m, _ in planned if m["layout"] == "blank"], [16, 17, 18, 19])
        self.assertEqual(planned[:15], self.pages[:15])
        self.assertEqual(planned[-1][0]["layout"], "backcover")
        self.assertEqual(planned[-1][0]["page"], 20)
        self.assertEqual(self.pages, original)

    def test_future_eighteen_leaves_two_blanks(self):
        pages = self.fixture(18)
        planned = build.plan_pages(pages)
        self.assertEqual([m["page"] for m, _ in planned if m["layout"] == "blank"], [18, 19])
        self.assertEqual(planned[:17], pages[:17])

    def test_full_twenty_needs_no_padding(self):
        pages = self.fixture(20)
        self.assertEqual(build.plan_pages(pages), pages)

    def test_legacy_sixteen_is_unchanged(self):
        for press in (False, True):
            self.assertEqual(build.plan_pages(self.pages, 16, press), self.pages)

    def test_eighteen_screen_and_press_counts(self):
        pages = self.fixture(18)
        self.assertEqual(build.plan_pages(pages, 18), pages)
        self.assertEqual(len(build.plan_pages(pages, 18, True)), 20)
        self.assertEqual(build.output_page_count(18, True), 20)

    def test_refuses_to_drop_source_pages(self):
        for count, target in ((18, 16), (20, 18)):
            with self.subTest(count=count, target=target), self.assertRaisesRegex(build.BuildError, "exceed"):
                build.plan_pages(self.fixture(count), target, True)

    def test_invalid_target(self):
        with self.assertRaises(build.BuildError):
            build.output_page_count(19)

    def test_output_names_do_not_collide(self):
        edition = {"snapshot_raw": "2026-10-16", "version": "1.3.1"}
        names = {build.pdf_name(edition, press, count).name
                 for press in (False, True) for count in build.PAGE_COUNTS}
        self.assertEqual(len(names), 6)
        self.assertIn("snarkypuss_2026-10-16_v1.3.1.pdf", names)
        self.assertIn("snarkypuss-press_2026-10-16_v1.3.1.pdf", names)
        self.assertIn("snarkypuss-p20-press_2026-10-16_v1.3.1.pdf", names)


class SourceValidationTests(unittest.TestCase):
    def load(self, markers):
        with tempfile.TemporaryDirectory() as tmp:
            content = Path(tmp)
            (content / "fixture.md").write_text("\n".join(
                f"<!-- page: {n} layout={layout} -->\nFixture content." for n, layout in markers),
                encoding="utf-8")
            with patch.object(build, "CONTENT", content):
                return build.load_pages()

    def test_gaps_and_duplicates_rejected(self):
        for numbers in ((1, 3, 4), (1, 2, 2)):
            with self.subTest(numbers=numbers), self.assertRaisesRegex(build.BuildError, "no gaps or duplicates"):
                self.load([(n, "standard") for n in numbers])

    def test_covers_required_at_ends(self):
        for layouts in (("standard", "backcover"), ("cover", "standard"),
                        ("cover", "backcover", "standard", "backcover")):
            with self.subTest(layouts=layouts), self.assertRaises(build.BuildError):
                self.load(list(enumerate(layouts, 1)))

    def test_spread_parity_and_partner_checks_survive(self):
        valid = [(1, "cover"), (2, "spread-left"), (3, "spread-right"), (4, "backcover")]
        self.assertEqual(len(self.load(valid)), 4)
        for layouts in (("cover", "standard", "spread-left", "spread-right", "backcover"),
                        ("cover", "spread-left", "standard", "backcover"),
                        ("cover", "standard", "spread-right", "backcover")):
            with self.subTest(layouts=layouts), self.assertRaisesRegex(build.BuildError, "spread"):
                self.load(list(enumerate(layouts, 1)))


class GenerationTests(unittest.TestCase):
    def test_generated_blanks_have_no_folios_and_back_cover_is_last(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(build, "BUILD", Path(tmp)):
            for count in build.PAGE_COUNTS:
                for press in (False, True):
                    with self.subTest(count=count, press=press):
                        pages = build.generate_tex(press=press, page_count=count)
                        tex = build.artifacts(press, count)[0].read_text(encoding="utf-8")
                        blanks = build.output_page_count(count, press) - 16
                        self.assertEqual(tex.count("% Blank padding page "), blanks)
                        self.assertEqual(tex.count(r"\thispagestyle{empty}\cropmarks\null\clearpage"), blanks)
                        self.assertEqual(len(re.findall(r"\\begin\{snarkypage\}", tex)), 14)
                        self.assertTrue(tex.rstrip().endswith(r"\backcoverpage{images/back-cover-plate.png}" + "\n" + r"\end{document}"))
                        self.assertEqual(len(pages), build.output_page_count(count, press))

    def test_clean_derived_pages_between_builds(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(build, "BUILD", Path(tmp)):
            build.generate_tex()
            stale = Path(tmp) / "pages-p20" / "99.md"
            stale.write_text("stale", encoding="utf-8")
            build.generate_tex()
            self.assertFalse(stale.exists())

    def test_legacy_tex_has_no_padding(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(build, "BUILD", Path(tmp)):
            pages = build.generate_tex(page_count=16)
            self.assertEqual(len(pages), 16)
            self.assertNotIn("% Blank padding page", build.artifacts(False, 16)[0].read_text())

    def test_cli_help_and_bad_page_count(self):
        script = str(Path(build.__file__))
        help_result = subprocess.run([sys.executable, script, "--help"], capture_output=True, text=True)
        self.assertEqual(help_result.returncode, 0)
        self.assertIn("--pages {16,18,20}", help_result.stdout)
        bad_result = subprocess.run([sys.executable, script, "--pages", "19"], capture_output=True, text=True)
        self.assertEqual(bad_result.returncode, 2)


class PDFValidationTests(unittest.TestCase):
    def test_pdfinfo_and_log_paths_use_selected_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(build, "ROOT", root), patch.object(build, "BUILD", root):
                for target in build.PAGE_COUNTS:
                    for press in (False, True):
                        count = build.output_page_count(target, press)
                        build.artifacts(press, target)[1].touch()
                        w, h = build.PRESS_PT if press else build.A5_PT
                        info = f"Pages: {count}\nPage size: {w} x {h} pts\n"
                        for pdfinfo in (None, "/usr/bin/pdfinfo"):
                            with self.subTest(target=target, press=press, pdfinfo=pdfinfo), \
                                    patch.object(build.shutil, "which", return_value=pdfinfo), \
                                    patch.object(build.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout=info)):
                                log = f"Output written on brochure.pdf ({count} pages, 100 bytes)."
                                self.assertEqual(build.validate_pdf(press, log, target), count)

    def test_wrong_count_or_geometry_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(build, "ROOT", root), patch.object(build, "BUILD", root):
                build.artifacts(True)[1].touch()
                for info in ("Pages: 18\nPage size: 464.882 x 640.63 pts\n",
                             "Pages: 20\nPage size: 419.528 x 595.276 pts\n"):
                    with patch.object(build.shutil, "which", return_value="pdfinfo"), \
                            patch.object(build.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout=info)), \
                            self.assertRaises(build.BuildError):
                        build.validate_pdf(True)
                with patch.object(build.shutil, "which", return_value=None), self.assertRaisesRegex(build.BuildError, "exactly 20"):
                    build.validate_pdf(True, "Output written on brochure.pdf (18 pages, 100 bytes).")


if __name__ == "__main__":
    unittest.main()
