"""The installer's translations: catalogs in step with English and the code that
reads them, drawable by the live console font, and the chosen language handed
to the installed system."""

import importlib.util
import json
import os
import re
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


def console_font():
    spec = importlib.util.spec_from_file_location("console_font", SHARE / "console-font.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.catalogs = catalogs()
        self.english = self.catalogs["en"]

    def test_every_translation_has_exactly_the_english_keys_and_placeholders(self):
        for code, catalog in self.catalogs.items():
            with self.subTest(code=code):
                self.assertEqual(sorted(catalog), sorted(self.english))
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


class ConsoleFontTest(unittest.TestCase):
    def test_the_live_console_font_draws_every_translated_string(self):
        registry = omarchy_file("default/i18n/locales.json")
        names = json.loads(registry.read_text()) if registry else {}
        module = console_font()
        for size in ("16", "32"):
            source = TERMINUS / f"ter-v{size}b.psf.gz"
            if not source.is_file():
                self.skipTest("terminus-font is not installed")
            import gzip

            width, height, glyphs, table = module.read_font(gzip.decompress(source.read_bytes()))
            module.patch(width, height, glyphs, table)
            drawable = {codepoint for codepoints in table for codepoint in codepoints}
            for code, catalog in catalogs().items():
                text = "".join(catalog.values()) + names.get(code, {}).get("name", "") + UI_GLYPHS
                missing = sorted({c for c in text if ord(c) > 0x7E and ord(c) not in drawable})
                with self.subTest(size=size, code=code):
                    self.assertEqual(missing, [])

    def test_half_blocks_fill_the_right_half_of_the_cell(self):
        module = console_font()
        upper = module.half_block(16, 32, True)
        self.assertEqual(upper[:2], b"\xff\xff")
        self.assertEqual(upper[-2:], b"\x00\x00")
        self.assertEqual(module.half_block(8, 16, False)[:8], bytes(8))


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


if __name__ == "__main__":
    unittest.main()
