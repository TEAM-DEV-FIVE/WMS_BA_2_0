# Native Apple Silicon lab application. PyInstaller signs embedded Mach-O ad-hoc.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

repo = Path(SPECPATH).parents[1]
datas = collect_data_files('apps.desktop.local_store', includes=['*.sql'])
datas += collect_data_files('apps.desktop.assets', includes=['*.png'])
datas += collect_data_files('certifi') + collect_data_files('pypdfium2')
datas += [(str(p), 'apps/desktop/assets') for p in (repo/'apps/server/printing_assets').iterdir()
          if p.suffix in {'.ttf', '.txt'}]
hidden = collect_submodules('apps.desktop') + collect_submodules('packages.contracts')
a = Analysis([str(repo/'apps/desktop/windows_entry.py')], pathex=[str(repo)],
             binaries=collect_dynamic_libs('pypdfium2_raw'), datas=datas, hiddenimports=hidden,
             excludes=['apps.server', 'sqlalchemy', 'psycopg', 'fastapi', 'uvicorn', 'pytest', 'reportlab'],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], name='WMS', console=False, exclude_binaries=True,
          strip=False, upx=False, target_arch='arm64', codesign_identity=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='WMS')
app = BUNDLE(coll, name='WMS.app', bundle_identifier='vn.interntechlead.wms.lab',
             icon=str(repo/'apps/desktop/assets/wms-logo.png'),
             info_plist={'CFBundleShortVersionString': '0.1.0',
                         'NSHighResolutionCapable': True, 'LSMinimumSystemVersion': '15.0'})
