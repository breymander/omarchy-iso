# Live console fonts

`configs/airootfs/usr/share/omarchy-iso/fonts/omarchy-live16.psf` (8x16) and
`omarchy-live32.psf` (16x32) are the live ISO's console fonts. `i18n.sh`
loads the one matching the cell size the kernel picked: 8x16 up to about
1920x1200, 16x32 from about 2256x1504.

They are DejaVu Sans Mono, regular at 8x16 and bold at 16x32, rendered into
the 512 characters kbd's Terminus (`ter-v`) carries. Terminus itself draws
several letters alike that readers of their scripts tell apart: б and Б,
y and u, υ and u, and it gives v and ν, п and π, γ and ү, ħ and ћ, - and –
a single glyph each. `dejavu-psf.py` says what it does about the glyphs that
do not fit the cell as drawn.

## Rebuilding

The outputs are committed; rebuild them only when an input changes, and
check that the hashes below still match before committing a new font.

Inputs:

| File | Source | SHA-256 |
|---|---|---|
| `dejavu-fonts-ttf-2.37.zip` | <https://github.com/dejavu-fonts/dejavu-fonts/releases/tag/version_2_37> | `7576310b219e04159d35ff61dd4a4ec4cdba4f35c00e002a136f00e96a908b0a` |
| `ter-v16b.psf.gz`, `ter-v32b.psf.gz` | Arch `terminus-font` 4.49.1-8, `/usr/share/kbd/consolefonts` | `ab9d74bc…0233`, `e27cd0f1…2e24` |
| FreeType | 2.13.2, as bundled in `freetype-py` 2.5.1 | |

```bash
python -m venv /tmp/fonts && /tmp/fonts/bin/pip install freetype-py==2.5.1
ttf=dejavu-fonts-ttf-2.37/ttf
fonts=configs/airootfs/usr/share/omarchy-iso/fonts
/tmp/fonts/bin/python builder/console-font/dejavu-psf.py $ttf/DejaVuSansMono.ttf,$ttf/DejaVuSans.ttf /usr/share/kbd/consolefonts/ter-v16b.psf.gz $fonts/omarchy-live16.psf 13 13
/tmp/fonts/bin/python builder/console-font/dejavu-psf.py $ttf/DejaVuSansMono-Bold.ttf,$ttf/DejaVuSans-Bold.ttf /usr/share/kbd/consolefonts/ter-v32b.psf.gz $fonts/omarchy-live32.psf 26 26
```

The arguments after the output are the pixel size (13 and 26 make DejaVu
Sans Mono's advance 8 and 16 pixels) and the baseline row (one row lower at
16x32 keeps the stacked accents of ΐ and ΰ inside the cell).

Outputs:

| File | SHA-256 |
|---|---|
| `omarchy-live16.psf` | `35f1f5122dd4757f7d181d762d54596d25d7e4acbcc2355527823ff2a0f227f0` |
| `omarchy-live32.psf` | `67018b3d83d83e31c10dca2cd78935532b38c02576c1a5788c670671fccf1736` |

What the build reports, at both sizes: Ҝ ҝ Ҡ ҡ Ҷ ҷ Ҹ ҹ come from DejaVu Sans;
Έ Ή Ҡ are narrowed, and at 16x32 also ď Ί Ҝ ҡ Ҷ ҷ Ҹ; Ύ gets its tonos
above; at 8x16 ĺ loses one pixel of its accent. Nothing else is clipped.
`test/unit/test_installer_i18n.py` rebuilds both fonts and compares them byte
for byte when freetype-py is installed and `DEJAVU_TTF_DIR` holds the TTFs.

## License

The fonts are derived from DejaVu, whose license is in
`configs/airootfs/usr/share/omarchy-iso/fonts/LICENSE`: Bitstream Vera, with
DejaVu's changes in the public domain. A modified font may not be called
Bitstream or Vera, which is why these are named omarchy-live. No Terminus
glyph is in them; Terminus supplies only the list of characters.
