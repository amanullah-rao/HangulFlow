# Third-party notices

HangulFlow includes or links to the following third-party components. Each
keeps its own license.

| Component | Used for | License |
|---|---|---|
| [Qt for Python (PySide6)](https://doc.qt.io/qtforpython-6/) and the Qt libraries | User interface, text-to-speech access | LGPL-3.0 (also GPL / commercial) |
| [Pretendard](https://github.com/orioncactus/pretendard) by Kil Hyung-jin | Korean and English text | SIL Open Font License 1.1 — `hangulflow/resources/fonts/OFL-Pretendard.txt` |
| [Noto Nastaliq Urdu](https://fonts.google.com/noto/specimen/Noto+Nastaliq+Urdu) by Google | Urdu text | SIL Open Font License 1.1 — `hangulflow/resources/fonts/OFL-NotoNastaliqUrdu.txt` |
| [Python](https://www.python.org/) | Runtime bundled in the Windows build | PSF License |
| [PyInstaller](https://pyinstaller.org/) bootloader | Windows build | GPL-2.0 with a bootloader exception that permits distributing the built app |

## Qt / PySide6 (LGPL-3.0)

The Windows build ships the Qt and PySide6 libraries unmodified, as separate
DLL and `.pyd` files in the `_internal` folder, so they can be replaced with
other compatible versions. Qt source code is available from
<https://download.qt.io/> and PySide6 source code from
<https://code.qt.io/cgit/pyside/pyside-setup.git/>. The LGPL-3.0 text is at
<https://www.gnu.org/licenses/lgpl-3.0.html>.

## Fonts

The fonts are bundled unmodified. The SIL Open Font License allows them to be
bundled and redistributed with software, provided the license text accompanies
them and the fonts are not sold on their own.

## Text-to-speech voices

Pronunciation uses the speech voices already installed in Windows (for example
"Microsoft Heami" for Korean). No voice data is bundled with HangulFlow.
