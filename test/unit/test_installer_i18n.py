"""The installer's translations: catalogs in step with English and the code that
reads them, drawable by the live console font, and the chosen language handed
to the installed system."""

import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHARE = ROOT / "configs/airootfs/usr/share/omarchy-iso"
I18N = SHARE / "i18n"
SOURCES = (
    ROOT / "configs/airootfs/root/configurator",
    ROOT / "configs/airootfs/usr/local/bin/omarchy-install-dashboard",
)
OMARCHY_CANDIDATES = (
    Path(os.environ.get("OMARCHY_PATH", "/nonexistent")),
    Path("/omarchy-source"),
    ROOT.parent / "omarchy",
    Path("/usr/share/omarchy"),
)
FONTS = SHARE / "fonts"
TERMINUS = Path("/usr/share/kbd/consolefonts")
PLACEHOLDER = re.compile(r"%\d")
# What the installer draws besides catalog text: the logo, gum's borders and spinner.
UI_GLYPHS = "▀▄█╭╮╰╯─│▒▓•›…—"

sys.path.insert(0, str(SHARE))
sys.modules.setdefault("orchestrator.archinstall_adapter", types.ModuleType("orchestrator.archinstall_adapter"))

from orchestrator import phases_impl  # noqa: E402
from orchestrator.context import validate_language  # noqa: E402


def catalogs():
    return {path.stem: json.loads(path.read_text()) for path in sorted(I18N.glob("*.json"))}


def omarchy_file(relative):
    for root in OMARCHY_CANDIDATES:
        if (root / relative).is_file():
            return root / relative
    return None


def console_fonts():
    """(width, height, glyph count, {character: glyph}) of each shipped console font."""
    for size in ("16", "32"):
        data = (FONTS / f"omarchy-live{size}.psf").read_bytes()
        assert data[:4] == b"\x72\xb5\x4a\x86", "not a PSF2 font"
        _, _, header, _, count, glyph_size, height, width = struct.unpack_from("<8I", data)
        glyphs = [data[header + i * glyph_size : header + (i + 1) * glyph_size] for i in range(count)]
        entries = data[header + count * glyph_size :].split(b"\xff")[:count]
        glyph = {char: glyphs[index] for index, entry in enumerate(entries)
                 for char in entry.split(b"\xfe")[0].decode("utf-8")}
        yield size, width, height, count, glyph


def pixels(glyph):
    return [(byte >> bit) & 1 for byte in glyph for bit in range(7, -1, -1)]


class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.catalogs = catalogs()
        self.english = self.catalogs["en"]

    def test_translations_only_carry_english_keys_with_their_placeholders(self):
        # A missing key is allowed and shows in English, so a new string never waits on 35 translations.
        for code, catalog in self.catalogs.items():
            with self.subTest(code=code):
                self.assertLessEqual(set(catalog), set(self.english))
                for key, text in catalog.items():
                    self.assertEqual(sorted(PLACEHOLDER.findall(text)), sorted(PLACEHOLDER.findall(self.english[key])), key)

    def test_strings_fit_the_console_and_the_places_they_are_printed(self):
        for code, catalog in self.catalogs.items():
            for key, text in catalog.items():
                with self.subTest(code=code, key=key):
                    self.assertTrue(text.strip(), "empty")
                    self.assertNotRegex(text, r"[\t\n\\]", "tabs, newlines and backslashes do not survive @tsv")
                    self.assertLessEqual(len(text), max(80, len(self.english[key]) + 10))
                    if key.startswith("summary.") and key != "summary.prompt":
                        self.assertNotIn(",", text, "the summary is a comma-separated gum table")
                    if key.startswith("form.") and key.endswith(".prompt"):
                        self.assertTrue(text.endswith("> "))

    def test_tips_fit_the_progress_screen_without_truncation(self):
        # The dashboard cuts the tip line at the logo's 81 columns.
        for code, catalog in self.catalogs.items():
            line = catalog.get("progress.tipLine", self.english["progress.tipLine"])
            for key, tip in catalog.items():
                if key.startswith("progress.tip."):
                    with self.subTest(code=code, key=key):
                        self.assertLessEqual(len(line.replace("%1", tip)), 80)

    def test_codes_are_omarchy_languages(self):
        registry = omarchy_file("default/i18n/locales.json")
        for code in self.catalogs:
            self.assertRegex(code, r"^[a-z]{2,3}(-[A-Z]{2})?$")
        if registry is None:
            self.skipTest("no Omarchy runtime to read the language registry from")
        self.assertLessEqual(set(self.catalogs), set(json.loads(registry.read_text())))

    def test_every_key_is_used_and_every_used_key_exists(self):
        used = set()
        for source in SOURCES:
            text = source.read_text()
            used |= set(re.findall(r"\bt ([a-z][A-Za-z]*(?:\.[A-Za-z]+)+)", text))
            used |= set(re.findall(r"^\s+(progress\.(?:whimsy|tip)\.[A-Za-z]+)$", text, re.MULTILINE))
        self.assertEqual(used - set(self.english), set())
        self.assertEqual({key for key in self.english if not key.startswith("form.")} - used, set())

    def test_form_strings_match_the_setup_form_they_translate(self):
        form = omarchy_file("install/provisioning/setup-form.sh")
        if form is None:
            self.skipTest("no Omarchy runtime to read the setup form from")
        text = form.read_text()
        for key, english in self.english.items():
            if key.startswith("form."):
                self.assertIn(f'"{english}"', text, key)


class LanguageDefaultsTest(unittest.TestCase):
    def setUp(self):
        self.defaults = json.loads((SHARE / "language-defaults.json").read_text())

    def test_every_language_in_the_picker_has_defaults(self):
        self.assertLessEqual(set(catalogs()), set(self.defaults))
        registry = omarchy_file("default/i18n/locales.json")
        if registry is None:
            self.skipTest("no Omarchy runtime to read the language registry from")
        self.assertEqual(set(self.defaults), set(json.loads(registry.read_text())))

    def test_every_keyboard_is_a_row_of_the_setup_form(self):
        form = omarchy_file("install/provisioning/setup-form.sh")
        if form is None:
            self.skipTest("no Omarchy runtime to read the setup form from")
        rows = re.search(r"OMARCHY_KEYBOARD_LAYOUTS=\$'(.*?)'\n", form.read_text(), re.DOTALL).group(1).splitlines()
        labels = {row.split("|")[0] for row in rows}
        for code, defaults in self.defaults.items():
            with self.subTest(code=code):
                self.assertIn(defaults["keyboard"], labels)

    def test_every_timezone_is_a_zone_the_timezone_list_offers(self):
        # timedatectl list-timezones offers tzdata's zones and links, read the same way here.
        tzdata = Path("/usr/share/zoneinfo/tzdata.zi")
        if not tzdata.is_file():
            self.skipTest("tzdata is not installed")
        zones = set()
        for line in tzdata.read_text().splitlines():
            fields = line.split()
            if fields[:1] == ["Z"]:
                zones.add(fields[1])
            elif fields[:1] == ["L"]:
                zones.add(fields[2])
        for code, defaults in self.defaults.items():
            if "timezone" in defaults:
                with self.subTest(code=code):
                    self.assertIn(defaults["timezone"], zones)


class ConsoleFontTest(unittest.TestCase):
    def test_the_live_console_fonts_draw_every_translated_string(self):
        registry = omarchy_file("default/i18n/locales.json")
        names = json.loads(registry.read_text()) if registry else {}
        for size, _, _, _, glyph in console_fonts():
            for code, catalog in catalogs().items():
                text = "".join(catalog.values()) + names.get(code, {}).get("name", "") + UI_GLYPHS
                missing = sorted({c for c in text if ord(c) > 0x7E and c not in glyph})
                with self.subTest(size=size, code=code):
                    self.assertEqual(missing, [])

    def test_each_font_fills_the_cell_the_kernel_picks(self):
        self.assertEqual([(w, h, n) for _, w, h, n, _ in console_fonts()], [(8, 16, 512), (16, 32, 512)])

    def test_letters_terminus_draws_alike_look_different(self):
        # Share of a pair's pixels that differ, of the inkier glyph's ink:
        # Terminus has 0.04 for б Б and υ u and 0.24 for y u at 16x32.
        for size, _, _, _, glyph in console_fonts():
            for pair in ("бБ", "υu", "yu"):
                a, b = pixels(glyph[pair[0]]), pixels(glyph[pair[1]])
                share = sum(x != y for x, y in zip(a, b)) / max(sum(a), sum(b))
                with self.subTest(size=size, pair=pair):
                    self.assertGreater(share, 0.3)

    def test_letters_terminus_shares_a_glyph_between_have_their_own(self):
        for size, _, _, _, glyph in console_fonts():
            for pair in ("vν", "пπ", "γү", "ħћ", "-–", "иu"):
                with self.subTest(size=size, pair=pair):
                    self.assertNotEqual(glyph[pair[0]], glyph[pair[1]])

    def test_cyrillic_ve_and_de_take_their_russian_forms(self):
        for size, width, height, _, glyph in console_fonts():
            row_bytes = (width + 7) // 8

            def rows(char):
                ink = [any(glyph[char][row * row_bytes:(row + 1) * row_bytes]) for row in range(height)]
                return ink.index(True), len(ink) - 1 - ink[::-1].index(True)

            with self.subTest(size=size):
                # в is a lowercase letter: as tall as а, not as В.
                self.assertEqual(rows("в")[0], rows("а")[0])
                self.assertLess(rows("В")[0], rows("в")[0])
                # д's foot reaches below the baseline, as у's tail does.
                self.assertGreater(rows("д")[1], rows("а")[1])

    def test_the_logo_blocks_fill_the_whole_or_half_the_cell(self):
        for size, width, height, _, glyph in console_fonts():
            half = width * height // 2
            with self.subTest(size=size):
                self.assertEqual(pixels(glyph["█"]), [1] * (2 * half))
                self.assertEqual(pixels(glyph["▀"]), [1] * half + [0] * half)
                self.assertEqual(pixels(glyph["▄"]), [0] * half + [1] * half)

    def test_the_fonts_rebuild_from_their_sources(self):
        ttf = Path(os.environ.get("DEJAVU_TTF_DIR", "/usr/share/fonts/TTF"))
        try:
            import freetype  # noqa: F401
        except ImportError:
            self.skipTest("freetype-py is not installed")
        if not (ttf / "DejaVuSansMono.ttf").is_file() or not (TERMINUS / "ter-v16b.psf.gz").is_file():
            self.skipTest("DejaVu or terminus-font is not installed")
        builds = {"16": ("DejaVuSansMono.ttf", "DejaVuSans.ttf", "13"),
                  "32": ("DejaVuSansMono-Bold.ttf", "DejaVuSans-Bold.ttf", "26")}
        with tempfile.TemporaryDirectory() as directory:
            for size, (mono, sans, ppem) in builds.items():
                output = Path(directory) / f"{size}.psf"
                subprocess.run([sys.executable, str(ROOT / "builder/console-font/dejavu-psf.py"),
                                f"{ttf / mono},{ttf / sans}", str(TERMINUS / f"ter-v{size}b.psf.gz"),
                                str(output), ppem, ppem], check=True, capture_output=True)
                with self.subTest(size=size):
                    self.assertEqual(output.read_bytes(), (FONTS / f"omarchy-live{size}.psf").read_bytes())


class ShellLookupTest(unittest.TestCase):
    def lookup(self, script, catalogs_dir):
        return subprocess.run(
            ["bash", "-c", f'source "{SHARE}/i18n.sh"; {script}'],
            env={**os.environ, "OMARCHY_ISO_I18N_DIR": str(catalogs_dir)},
            capture_output=True, text=True, check=True,
        ).stdout

    def test_placeholders_fallback_and_form_text(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            (directory / "en.json").write_text(json.dumps({"a.b": "Disk %1 has %2", "a.only": "English only", "form.x": "Username> "}))
            (directory / "da.json").write_text(json.dumps({"a.b": "%2 på %1 & mere", "form.x": "Brugernavn> "}))
            self.assertEqual(self.lookup('i18n_load da; t a.b /dev/sda 32GB', directory), "32GB på /dev/sda & mere")
            self.assertEqual(self.lookup('i18n_load da; t a.only', directory), "English only")
            self.assertEqual(self.lookup('i18n_load da; printf %s "${OMARCHY_ISO_FORM_TEXT["Username> "]}"', directory), "Brugernavn> ")
            self.assertEqual(self.lookup('i18n_load ../da; t a.b x y', directory), "Disk x has y")


class ConsoleFontLoadTest(unittest.TestCase):
    def load(self, probe):
        with tempfile.TemporaryDirectory() as directory:
            stubs = Path(directory)
            (stubs / "showconsolefont").write_text(f"#!/bin/bash\n{probe}\n")
            (stubs / "setfont").write_text(f'#!/bin/bash\necho "$@" > {stubs}/setfont.args\n')
            for tool in ("showconsolefont", "setfont"):
                (stubs / tool).chmod(0o755)
            result = subprocess.run(
                ["bash", "-c", f'set -euo pipefail; source "{SHARE}/i18n.sh"; i18n_console_font /dev/tty1; echo survived'],
                env={**os.environ, "PATH": f"{stubs}:{os.environ['PATH']}"}, capture_output=True, text=True,
            )
            args = (stubs / "setfont.args").read_text().split() if (stubs / "setfont.args").exists() else []
            return result.stdout, args

    def test_the_font_follows_the_cell_size_the_kernel_picked(self):
        self.assertEqual(self.load("echo 16x32x512")[1][-1], str(FONTS / "omarchy-live32.psf"))
        self.assertEqual(self.load("echo 8x16x512")[1][-1], str(FONTS / "omarchy-live16.psf"))

    def test_a_failing_font_probe_never_stops_a_strict_caller(self):
        stdout, args = self.load("exit 1")
        self.assertEqual(stdout, "survived\n")
        self.assertEqual(args[-1], str(FONTS / "omarchy-live16.psf"))


class LanguageMarkerTest(unittest.TestCase):
    def marker(self, language):
        with tempfile.TemporaryDirectory() as directory:
            ctx = types.SimpleNamespace(target=Path(directory), omarchy_install={"language": language})
            phases_impl._write_language_marker(ctx)
            marker = Path(directory) / "etc/omarchy/language"
            return marker.read_text() if marker.exists() else None

    def test_a_chosen_language_reaches_the_target_and_english_writes_nothing(self):
        self.assertEqual(self.marker("da"), "da\n")
        self.assertEqual(self.marker("zh-CN"), "zh-CN\n")
        self.assertIsNone(self.marker("en"))
        self.assertIsNone(self.marker(None))

    def test_only_registry_codes_are_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = Path(directory) / "locales.json"
            registry.write_text(json.dumps({"en": {}, "da": {}, "zh-CN": {}}))
            for code in ("da", "zh-CN", "", None):
                validate_language(code, registry)
            for code in ("xx", "../da", "da\n", 7):
                with self.subTest(code=code), self.assertRaises(RuntimeError):
                    validate_language(code, registry)

    def test_without_a_registry_only_english_is_accepted(self):
        missing = Path("/nonexistent/locales.json")
        validate_language("en", missing)
        with self.assertRaises(RuntimeError):
            validate_language("da", missing)


if __name__ == "__main__":
    unittest.main()
