"""Build a disposable PostgreSQL catalog from migrations for report diagrams.

Single-user mode needs no listening socket and never connects to the live WMS DB.
Only schema and seed permission metadata are exported, never user/warehouse rows.
"""

import argparse
import csv
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = """
SELECT jsonb_build_object(
 'tables', (SELECT jsonb_agg(jsonb_build_object(
   'name', c.relname,
   'columns', (SELECT jsonb_agg(jsonb_build_object(
     'name', a.attname, 'type', format_type(a.atttypid,a.atttypmod),
     'nullable', NOT a.attnotnull, 'default', pg_get_expr(d.adbin,d.adrelid)
   ) ORDER BY a.attnum) FROM pg_attribute a LEFT JOIN pg_attrdef d
     ON d.adrelid=a.attrelid AND d.adnum=a.attnum
     WHERE a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped),
   'constraints', COALESCE((SELECT jsonb_agg(jsonb_build_object(
     'name', k.conname, 'kind', k.contype, 'definition', pg_get_constraintdef(k.oid),
     'columns', (SELECT jsonb_agg(a.attname ORDER BY u.ord)
       FROM unnest(k.conkey) WITH ORDINALITY u(num,ord)
       JOIN pg_attribute a ON a.attrelid=k.conrelid AND a.attnum=u.num),
     'target', (SELECT relname FROM pg_class WHERE oid=k.confrelid),
     'target_columns', (SELECT jsonb_agg(a.attname ORDER BY u.ord)
       FROM unnest(k.confkey) WITH ORDINALITY u(num,ord)
       JOIN pg_attribute a ON a.attrelid=k.confrelid AND a.attnum=u.num)
   ) ORDER BY k.conname) FROM pg_constraint k WHERE k.conrelid=c.oid), '[]'::jsonb),
   'indexes', (SELECT jsonb_agg(indexdef ORDER BY indexname) FROM pg_indexes
               WHERE schemaname='wms' AND tablename=c.relname)
 ) ORDER BY c.relname) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
   WHERE n.nspname='wms' AND c.relkind='r'),
 'roles', (SELECT jsonb_agg(jsonb_build_object('code',code,'name',name) ORDER BY code) FROM wms.role),
 'permissions', (SELECT jsonb_agg(jsonb_build_object('code',code,'scope_kind',scope_kind,
                    'description',description) ORDER BY code) FROM wms.permission),
 'role_permissions', (SELECT jsonb_agg(jsonb_build_object('role',r.code,'permission',p.code)
                    ORDER BY r.code,p.code) FROM wms.role_permission rp
                    JOIN wms.role r ON r.id=rp.role_id JOIN wms.permission p ON p.id=rp.permission_id)
) AS snapshot
"""


def run(command, **kwargs):
    result = subprocess.run(command, capture_output=True, text=True, check=False, **kwargs)
    if result.returncode or re.search(r"(?:ERROR|FATAL|PANIC):", result.stderr):
        raise RuntimeError(result.stderr[-4000:])
    return result


def export(pg_bin):
    migrations = sorted((ROOT / 'migrations').glob('*.sql'))
    with tempfile.TemporaryDirectory(prefix='wms-report-schema-') as directory:
        directory = Path(directory)
        cluster = directory / 'cluster'
        run([str(pg_bin / 'initdb'), '-D', str(cluster), '--no-sync', '--auth=trust'])
        statements = []
        for path in migrations:
            lines = path.read_text().splitlines()
            meaningful = [i for i, line in enumerate(lines) if line.strip() and not line.lstrip().startswith('--')]
            if lines[meaningful[0]].strip() == 'BEGIN;' and lines[meaningful[-1]].strip() == 'COMMIT;':
                lines[meaningful[0]] = lines[meaningful[-1]] = ''
            statements.append('\n'.join(lines))
        target = directory / 'catalog.hex'
        query = f"COPY (SELECT encode(convert_to(snapshot::text,'UTF8'),'hex') FROM ({CATALOG}) q) TO '{target}';"
        run([str(pg_bin / 'postgres'), '--single', '-j', '-D', str(cluster), 'postgres'],
            input='BEGIN;\n' + '\n'.join(statements) + '\nCOMMIT;\n' + query + '\n\n')
        snapshot = json.loads(bytes.fromhex(target.read_text().strip()).decode())
    snapshot['basis'] = 'PostgreSQL catalog after applying repository migrations in a disposable single-user cluster'
    snapshot['schema'] = 'wms'
    snapshot['migrations'] = [{'file': p.relative_to(ROOT).as_posix(), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                              for p in migrations]
    snapshot['counts'] = {
        'tables': len(snapshot['tables']),
        'columns': sum(len(t['columns']) for t in snapshot['tables']),
        'foreign_keys': sum(c['kind'] == 'f' for t in snapshot['tables'] for c in t['constraints']),
        'roles': len(snapshot['roles']), 'permissions': len(snapshot['permissions']),
    }
    return snapshot


def write(snapshot):
    dest = ROOT / '02_CSDL/current'
    dest.mkdir(exist_ok=True)
    (dest / 'schema.json').write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n')
    with (dest / 'dictionary.csv').open('w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['table', 'column', 'data_type', 'nullable', 'default', 'primary_key', 'references'])
        for table in snapshot['tables']:
            pk = {col for c in table['constraints'] if c['kind'] == 'p' for col in c['columns']}
            refs = {col: c['target'] + '.' + target for c in table['constraints'] if c['kind'] == 'f'
                    for col, target in zip(c['columns'], c['target_columns'])}
            for col in table['columns']:
                writer.writerow([table['name'], col['name'], col['type'], 'YES' if col['nullable'] else 'NO',
                                 col['default'] or '', 'YES' if col['name'] in pk else 'NO', refs.get(col['name'], '')])
    lines = ['// Generated from PostgreSQL catalog. Full checks and indexes: schema.json.', '']
    for table in snapshot['tables']:
        lines.append('Table wms.' + table['name'] + ' {')
        pk = next((c['columns'] for c in table['constraints'] if c['kind'] == 'p'), [])
        for col in table['columns']:
            dtype = col['type']
            if ' ' in dtype:
                dtype = '"' + dtype + '"'
            opts = ['not null'] if not col['nullable'] else []
            if pk == [col['name']]:
                opts.append('pk')
            lines.append('  ' + col['name'] + ' ' + dtype + (' [' + ', '.join(opts) + ']' if opts else ''))
        if len(pk) > 1:
            lines.extend(['  indexes {', '    (' + ', '.join(pk) + ') [pk]', '  }'])
        lines.extend(['}', ''])
    for table in snapshot['tables']:
        for constraint in table['constraints']:
            if constraint['kind'] == 'f':
                def cols(items):
                    return items[0] if len(items) == 1 else '(' + ', '.join(items) + ')'
                lines.append(f"Ref: wms.{table['name']}.{cols(constraint['columns'])} > "
                             f"wms.{constraint['target']}.{cols(constraint['target_columns'])}")
    (dest / 'wms.dbml').write_text('\n'.join(lines) + '\n')
    (ROOT / '04_Phan_quyen/current_permissions.json').write_text(json.dumps(
        {key: snapshot[key] for key in ('roles', 'permissions', 'role_permissions')}, ensure_ascii=False, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pg-bin', type=Path, default=Path('/usr/lib/postgresql/16/bin'))
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    snapshot = export(args.pg_bin)
    if args.check:
        actual = json.loads((ROOT / '02_CSDL/current/schema.json').read_text())
        if actual != snapshot:
            raise SystemExit('Current schema snapshot differs from migration catalog')
    else:
        write(snapshot)
    print(json.dumps(snapshot['counts']))


if __name__ == '__main__':
    main()
