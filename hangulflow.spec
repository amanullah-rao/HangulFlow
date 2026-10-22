# PyInstaller build recipe for HangulFlow.
#
#   .venv\Scripts\python.exe -m PyInstaller hangulflow.spec --noconfirm --clean
#
# Produces dist\HangulFlow\HangulFlow.exe (one-folder build: starts faster than
# a one-file build and is less often flagged by antivirus heuristics).

a = Analysis(
    ["main.py"],
    datas=[
        ("hangulflow/resources", "hangulflow/resources"),  # word list + bundled fonts (with their licenses)
        ("LICENSE", "."),
        ("THIRD_PARTY_NOTICES.md", "."),
    ],
    excludes=["tkinter", "unittest", "pytest", "pydoc", "PySide6.QtQml", "PySide6.QtQuick"],
    noarchive=False,
)

# Qt pulls in parts HangulFlow never uses; leaving them out saves ~60 MB.
# (Pronunciation still works: the Windows voices don't need FFmpeg - check with
#  "HangulFlow.exe --self-test" after building.)
UNUSED = (
    "opengl32sw.dll",                                            # software OpenGL fallback
    "avcodec", "avformat", "avutil", "swresample", "swscale",    # FFmpeg (video/audio codecs)
    "ffmpegmediaplugin",
    "qt6quick", "qt6qml", "qt6pdf", "qpdf.dll", "qt6virtualkeyboard", "qtvirtualkeyboard",
)
a.binaries = [b for b in a.binaries if not any(name in b[0].lower() for name in UNUSED)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HangulFlow",
    console=False,  # windowed app: no console window
    icon="assets/hangulflow.ico",
    upx=False,
)

coll = COLLECT(exe, a.binaries, a.datas, name="HangulFlow", upx=False)
