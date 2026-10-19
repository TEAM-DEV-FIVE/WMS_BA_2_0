# Native Windows local server/first-run UI. Desktop remains a separate original bundle.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

repo = Path(SPECPATH).parents[1]
product = 'WMS'
datas = collect_data_files('mysql_migrations', includes=['*.json'])
datas += collect_data_files('migrations', includes=['*.sql'])
datas += collect_data_files('apps.local_launcher', includes=['*.json'])
datas += collect_data_files('apps.server.printing_assets')
datas += collect_data_files('apps.desktop.assets', includes=['*.png', '*.jpeg', '*.txt'])
datas += collect_data_files('certifi') + collect_data_files('tzdata')
for name in ('sqlglot', 'pydantic', 'sqlalchemy', 'fastapi'):
    datas += copy_metadata(name)
hidden = collect_submodules('apps.server') + collect_submodules('packages')
hidden += collect_submodules('apps.local_launcher') + ['pymysql', 'sqlalchemy.dialects.mysql.pymysql', 'mysql_migrations', 'migrations']
a = Analysis([str(repo/'apps/local_launcher/entry.py')], pathex=[str(repo)], datas=datas,
             hiddenimports=hidden, excludes=['pytest', 'IPython', 'matplotlib'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=product+'Local', console=False,
          icon=str(repo/'apps/desktop/assets/wms-app-icon.ico'), strip=False, upx=False,
          manifest=str(repo/'packaging/windows/app.manifest'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=product+'Local')
