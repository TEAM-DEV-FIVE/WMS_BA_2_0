# Build only from the pinned Windows x64 venv. No server package or credentials.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

repo = Path(SPECPATH).parents[1]
datas = collect_data_files('apps.desktop.local_store', includes=['*.sql'])
datas += collect_data_files('certifi') + collect_data_files('pypdfium2')
datas += [(str(p), 'apps/desktop/assets') for p in (repo/'apps/server/printing_assets').iterdir()
          if p.suffix in {'.ttf', '.txt'}]
hidden = collect_submodules('apps.desktop') + collect_submodules('packages.contracts')
a = Analysis([str(repo/'apps/desktop/windows_entry.py')], pathex=[str(repo)],
             binaries=collect_dynamic_libs('pypdfium2_raw'), datas=datas, hiddenimports=hidden,
             excludes=['apps.server', 'sqlalchemy', 'psycopg', 'fastapi', 'uvicorn', 'pytest', 'reportlab'],
             noarchive=False)
pyz = PYZ(a.pure)
common = dict(exclude_binaries=True, debug=False, bootloader_ignore_signals=False,
              strip=False, upx=False, manifest=str(repo/'packaging/windows/app.manifest'))
gui = EXE(pyz, a.scripts, [], name='WMS', console=False, **common)
helper = EXE(pyz, a.scripts, [], name='WMSHelper', console=True, **common)
coll = COLLECT(gui, helper, a.binaries, a.datas, strip=False, upx=False, name='WMS')
