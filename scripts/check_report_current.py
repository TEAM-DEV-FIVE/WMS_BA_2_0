"""Check report evidence against navigation, migrations, catalog and diagram outputs."""

import ast
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

import pypdfium2 as pdfium
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return json.loads((ROOT / name).read_text())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    module = ast.parse((ROOT / 'apps/desktop/views/admin_workspace.py').read_text())
    sections = next(ast.literal_eval(n.value) for n in module.body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'SECTIONS' for t in n.targets))
    keys = {s[1] for s in sections}
    features = read('01_Tai_lieu/current_features.json')
    captures = read('assets/readme/screenshots.json')
    require({x['key'] for x in features} == keys, 'Feature inventory differs from navigation')
    require(Counter(x['feature'] for x in captures) == Counter([*keys, 'login']), 'Screenshot coverage')
    readme = (ROOT / 'README.md').read_text()
    for row in captures:
        path = ROOT / row['file']
        require(hashlib.sha256(path.read_bytes()).hexdigest() == row['sha256'], f'Changed image: {path}')
        require(row['file'] in readme, f'Image missing in README: {path}')
        with Image.open(path) as img:
            require(img.width >= 800 and img.height >= 500, f'Insufficient screenshot size: {path}')
            img.verify()
    for row in features:
        require((ROOT / row['source']).exists(), 'Missing feature source: ' + row['source'])
    require('apps/desktop/assets/wms-logo-navy.png' in readme.split('# WMS')[0], 'Logo not above title')

    schema = read('02_CSDL/current/schema.json')
    require({m['file'] for m in schema['migrations']} ==
            {p.relative_to(ROOT).as_posix() for p in (ROOT / 'migrations').glob('[0-9]*.sql')},
            'Migration inventory differs')
    for row in schema['migrations']:
        require(hashlib.sha256((ROOT / row['file']).read_bytes()).hexdigest() == row['sha256'],
                'Migration changed: ' + row['file'])
    tables = schema['tables']
    require(schema['counts']['columns'] == sum(len(t['columns']) for t in tables), 'Column count')
    require(schema['counts']['tables'] == len(tables), 'Table count')
    graphs = read('03_So_do/Hien_hanh/diagram_sources.json')
    by_code = {g['code']: g for g in graphs}
    require(len(by_code) == len(graphs), 'Duplicate diagram code')
    require({c.removeprefix('ERD_') for c in by_code if c.startswith('ERD_')} ==
            {t['name'] for t in tables}, 'ERD coverage differs from schema')
    fk_count = 0
    for table in tables:
        name = table['name']
        diagram = by_code['ERD_' + name]
        require(len(diagram['nodes'][name]['lines']) == len(table['columns']), 'Missing ERD columns: ' + name)
        expected = Counter((name, c['target'], ', '.join(c['columns']) + ' → ' + ', '.join(c['target_columns']))
                           for c in table['constraints'] if c['kind'] == 'f')
        require(Counter(tuple(e) for e in diagram['edges']) == expected, 'FK mismatch: ' + name)
        fk_count += expected.total()
    require(fk_count == schema['counts']['foreign_keys'], 'FK count')
    for role in schema['roles']:
        diagram = by_code['ROLE_' + role['code']]
        shown = [line.split(' [')[0] for key, node in diagram['nodes'].items() if key != 'role'
                 for line in node['lines'] if re.search(r' \[[A-Z_]+\]$', line)]
        expected = [grant['permission'] for grant in schema['role_permissions'] if grant['role'] == role['code']]
        require(Counter(shown) == Counter(expected), 'Role diagram differs from seed: ' + role['code'])
    for graph in graphs:
        for source in graph['sources']:
            if '*' not in source and '…' not in source:
                require((ROOT / source).exists(), 'Missing diagram source: ' + source)
        if graph['code'].startswith('CLASS_'):
            for name, node in graph['nodes'].items():
                tree = ast.parse((ROOT / node['lines'][0]).read_text())
                require(any(isinstance(n, ast.ClassDef) and n.name == name for n in tree.body),
                        'Class no longer exists: ' + name)
        ET.parse(ROOT / f"03_So_do/Hien_hanh/svg/{graph['code']}.svg")
    drawio = ET.parse(ROOT / '03_So_do/Hien_hanh/WMS_Hien_hanh.drawio')
    require({d.get('id') for d in drawio.findall('diagram')} == set(by_code), 'draw.io coverage')
    with pdfium.PdfDocument(ROOT / '03_So_do/Hien_hanh/WMS_Hien_hanh.pdf') as pdf:
        require(len(pdf) == len(graphs) + (len(graphs) + 29) // 30, 'PDF page count')
        for index in range(len(pdf)):
            page = pdf[index]
            textpage = page.get_textpage()
            require(bool(textpage.get_text_range().strip()), f'Empty PDF page: {index + 1}')
            textpage.close()
            page.close()

    docs = ['README.md', '01_Tai_lieu/HIEN_TRANG_BAO_CAO.md', '01_Tai_lieu/ARCHITECTURE.md',
            '01_Tai_lieu/BA/03_SRS.md', '02_CSDL/README.md', '03_So_do/README.md',
            '03_So_do/RUNTIME_GUIDE.md', '03_So_do/NOTATION_GUIDE.md', '01_Tai_lieu/DOCUMENTATION.md',
            '03_So_do/Hien_hanh/index.md', '05_API/README.md', '05_API/README_BASELINE.md',
            '07_Kiem_tra/release/README.md']
    for filename in docs:
        path = ROOT / filename
        content = path.read_text()
        links = re.findall(r'\]\(([^)]+)\)', content) + re.findall(r'(?:src|href)="([^"]+)"', content)
        for link in links:
            if link.startswith(('https://', 'http://', '#', 'mailto:')):
                continue
            target = unquote(link.split('#')[0].strip('<>'))
            require((path.parent / target).exists(), f'Broken link in {filename}: {target}')
    api = read('05_API/openapi_runtime.json')
    operations = sum(method in {'get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace'}
                     for path in api['paths'].values() for method in path)
    require(str(len(api['paths'])) in readme and str(operations) in readme, 'README API counts')
    print(f'PASS: {len(features)} features, {len(captures)} authentic capture hashes, '
          f'{len(graphs)} diagrams, {len(tables)} tables, {fk_count} FKs; PDF and links valid')


if __name__ == '__main__':
    main()
