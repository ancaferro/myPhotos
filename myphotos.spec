# PyInstaller spec: single-file windowed executable with bundled models/.

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('models', 'models'),
    ],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='myPhotos',
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon='assets/icon.ico',
)
