from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError, IntegrityError

from apps.server.application.stock_identity import resolve_stock_identity
from apps.server.domain.errors import DomainError
from packages.contracts.traceability import COMPANY_OWNER, UNCLASSIFIED_OWNER

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def trace(iam):
    user, _ = iam.user('keeper')
    warehouse = iam.warehouse('TRACE')
    iam.grant(user, 'MASTER_DATA')
    grant = iam.grant(user, 'WAREHOUSE_MANAGER', warehouse)
    headers = iam.headers(iam.login('keeper'))

    class TraceFixture:
        engine = iam.engine
        client = iam.client

        def __init__(self):
            self.iam, self.user, self.warehouse = iam, user, warehouse
            self.headers, self.grant = headers, grant
            self.location, self.external = uuid4(), uuid4()
            with self.engine.begin() as c:
                c.execute(text("INSERT INTO wms.location(id,warehouse_id,code,name,kind,is_active) VALUES (:id,:wh,'TRACE-RECEIVING','Nhận hàng','RECEIVING',true)"), {'id': self.location, 'wh': warehouse})
                c.execute(text("INSERT INTO wms.location(id,code,name,kind,is_active) VALUES (:id,'TRACE-EXTERNAL','Bên ngoài','EXTERNAL',true)"), {'id': self.external})
            self.supplier = self.create('partners', code='NCC-01', name='Nhà cung cấp giả', is_supplier=True)['id']

        def create(self, resource, **body):
            r = self.client.post('/api/v1/master/' + resource, json={'reason': 'Fixture kiểm thử', **body},
                                 headers={**self.headers, 'Idempotency-Key': str(uuid4())})
            assert r.status_code == 201, r.text
            return r.json()

        def product(self, tracking='NONE'):
            unit = self.create('uoms', code=uuid4().hex[:20], name='Chiếc', decimal_places=0)
            return self.create('products', sku=uuid4().hex, name='Thiết bị giả', base_uom_id=unit['id'], tracking=tracking)

        def consignment(self):
            owner = self.create('stock-owners', code='OWNER-01', name='Chủ hàng giả', partner_id=self.supplier)
            agreement = self.create('consignment-agreements', code='AGREE-01', owner_id=owner['id'], warehouse_id=str(self.warehouse),
                                    valid_from='2026-01-01', valid_until='2027-12-31', source_ref='Hợp đồng giả CG-01')
            return owner, agreement

        def receipt(self, product=None, qty=1, owner=COMPANY_OWNER, agreement=None, serial_code=None):
            p = product or self.product('SERIAL' if serial_code else 'NONE')
            serial, doc, line, txn, move = (uuid4() if serial_code else None), uuid4(), uuid4(), uuid4(), uuid4()
            with self.engine.begin() as c:
                if serial:
                    c.execute(text('INSERT INTO wms.serial(id,product_id,code) VALUES (:id,:product,:code)'), {'id': serial, 'product': p['id'], 'code': serial_code})
                item = resolve_stock_identity(c, product_id=UUID(p['id']), owner_id=UUID(str(owner)), warehouse_id=self.warehouse,
                                              business_date=iam.now.date(), serial_id=serial, consignment_id=UUID(agreement) if agreement else None)
                c.execute(text("""INSERT INTO wms.document
                    (id,number,kind,status,warehouse_id,partner_id,business_date,created_by,created_at,version,attributes)
                    VALUES (:id,:number,'RECEIPT','COMPLETED',:wh,:supplier,:day,:actor,:now,1,'{}')"""),
                          {'id': doc, 'number': 'TEST-' + doc.hex, 'wh': self.warehouse, 'supplier': self.supplier,
                           'day': iam.now.date(), 'actor': user, 'now': iam.now})
                c.execute(text("""INSERT INTO wms.document_line
                    (id,document_id,line_no,product_id,uom_id,quantity,factor_snapshot,base_quantity,owner_id,consignment_id)
                    VALUES (:id,:doc,1,:product,:unit,:qty,1,:qty,:owner,:agreement)"""),
                          {'id': line, 'doc': doc, 'product': p['id'], 'unit': p['base_uom_id'], 'qty': qty, 'owner': owner, 'agreement': agreement})
                c.execute(text("""INSERT INTO wms.inventory_transaction
                    (id,document_id,execution_key,operation,business_date,posted_at,posted_by)
                    VALUES (:id,:doc,:key,'RECEIVE',:day,:now,:actor)"""),
                          {'id': txn, 'doc': doc, 'key': uuid4(), 'day': iam.now.date(), 'now': iam.now, 'actor': user})
                c.execute(text("""INSERT INTO wms.stock_move
                    (id,transaction_id,line_id,stock_item_id,source_location_id,destination_location_id,quantity_base,base_uom_id)
                    VALUES (:id,:txn,:line,:item,:source,:dest,:qty,:unit)"""),
                          {'id': move, 'txn': txn, 'line': line, 'item': item, 'source': self.external,
                           'dest': self.location, 'qty': qty, 'unit': p['base_uom_id']})
                c.execute(text("""INSERT INTO wms.stock_balance(id,stock_item_id,location_id,on_hand,reserved,version)
                    VALUES (:id,:item,:location,:qty,0,1)"""), {'id': uuid4(), 'item': item, 'location': self.location, 'qty': qty})
            return dict(product=p, serial=serial, item=item, document=doc, line=line, transaction=txn, move=move)

        def read(self, receipt, headers=None, warehouse=None):
            return self.client.get(f"/api/v1/serials/{receipt['serial']}/warranty", params={'warehouse_id': warehouse or self.warehouse}, headers=headers or self.headers)

        def record(self, receipt, *, version=0, key=None, headers=None, **changes):
            return self.client.post(f"/api/v1/serials/{receipt['serial']}/warranty-records",
                                    headers={**(headers or self.headers), 'Idempotency-Key': str(key or uuid4())},
                                    json={'expected_version': version, 'receipt_move_id': str(receipt['move']),
                                          'reason': 'Đối chiếu chứng từ giả', **changes})

    return TraceFixture()


def test_owned_and_consigned_inventory_remain_ten_and_five_with_reconciliation(trace):
    owner, agreement = trace.consignment()
    product = trace.product()
    owned = trace.receipt(product, qty=10)
    consigned = trace.receipt(product, qty=5, owner=owner['id'], agreement=agreement['id'])
    assert owned['item'] != consigned['item']
    r = trace.client.get('/api/v1/stock-ownership', params={'warehouse_id': trace.warehouse, 'location_id': trace.location,
                        'stock_item_id': owned['item']}, headers=trace.headers)
    assert r.status_code == 200, r.text
    assert (r.json()['physical_base'], r.json()['owned_base'], r.json()['unclassified_base']) == ('15.000000', '10.000000', '0.000000')
    assert r.json()['consigned_by_owner'] == [{'owner_id': owner['id'], 'owner_partner_id': trace.supplier, 'quantity_base': '5.000000'}]
    raw = trace.engine.raw_connection()
    try:
        with raw.cursor() as cursor:
            for file in ['reconcile.sql', 'reconcile_ownership.sql']:
                cursor.execute((ROOT / '02_CSDL' / file).read_text())
                while True:
                    if cursor.description:
                        assert cursor.fetchall() == []
                    if not cursor.nextset():
                        break
    finally:
        raw.close()
    with pytest.raises(RuntimeError), trace.engine.begin() as c:
        c.execute(text('UPDATE wms.stock_balance SET on_hand=99 WHERE stock_item_id=:id'), {'id': consigned['item']})
        raise RuntimeError('rollback fixture')
    with trace.engine.connect() as c:
        assert dict(c.execute(text('SELECT stock_item_id,on_hand FROM wms.stock_balance')).tuples().all()) == {owned['item']: 10, consigned['item']: 5}


def test_owner_agreement_validation_and_history_are_enforced(trace):
    owner, agreement = trace.consignment()
    receipt = trace.receipt(qty=5, owner=owner['id'], agreement=agreement['id'])
    body = {**{k:v for k,v in agreement.items() if k not in {'id','version'}}, 'expected_version':1,
            'valid_until':'2030-01-01','reason':'Thử đổi lịch sử'}
    r = trace.client.put('/api/v1/master/consignment-agreements/' + agreement['id'], json=body,
                         headers={**trace.headers,'Idempotency-Key':str(uuid4())})
    assert r.status_code == 409 and r.json()['code'] == 'AGREEMENT_IN_USE'
    for sql, params in [
        ('UPDATE wms.stock_item SET owner_id=:owner,consignment_id=NULL WHERE id=:id', {'owner':COMPANY_OWNER,'id':receipt['item']}),
        ("UPDATE wms.consignment_agreement SET source_ref='New evidence' WHERE id=:id", {'id':agreement['id']}),
        ('UPDATE wms.stock_owner SET partner_id=NULL WHERE id=:id', {'id':owner['id']}),
    ]:
        with pytest.raises(IntegrityError), trace.engine.begin() as c:
            c.execute(text(sql), params)
    for override in [{'owner_id':COMPANY_OWNER,'consignment_id':UUID(agreement['id'])},
                     {'owner_id':UUID(owner['id'])}, {'owner_id':UNCLASSIFIED_OWNER},
                     {'owner_id':UUID(owner['id']),'consignment_id':UUID(agreement['id']),'business_date':date(2030,1,1)},
                     {'owner_id':UUID(owner['id']),'consignment_id':UUID(agreement['id']),'warehouse_id':uuid4()}]:
        args=dict(product_id=UUID(receipt['product']['id']),owner_id=COMPANY_OWNER,warehouse_id=trace.warehouse,business_date=date(2026,10,2))
        args.update(override)
        with pytest.raises(DomainError), trace.engine.begin() as c:
            resolve_stock_identity(c, **args)


def test_stock_read_alone_or_other_warehouse_never_reveals_owners(trace):
    row = trace.receipt(qty=10)
    user, _ = trace.iam.user('buyer')
    trace.iam.grant(user,'BUYER',trace.warehouse)
    other = trace.iam.warehouse('OTHER')
    trace.iam.grant(user,'CONTROLLER',other)
    headers = trace.iam.headers(trace.iam.login('buyer'))
    params = {'warehouse_id':trace.warehouse,'location_id':trace.location,'stock_item_id':row['item']}
    assert trace.client.get('/api/v1/stock-ownership',params=params,headers=headers).status_code == 404
    params['warehouse_id'] = other
    assert trace.client.get('/api/v1/stock-ownership',params=params,headers=headers).status_code == 404


def test_serial_cannot_occupy_two_owners_at_once_even_with_two_connections(trace):
    product = trace.product('SERIAL')
    owner, agreement = trace.consignment()
    serial, second_location = uuid4(), uuid4()
    with trace.engine.begin() as c:
        c.execute(text("INSERT INTO wms.location(id,warehouse_id,code,name,kind,is_active) VALUES (:id,:wh,'SECOND-RECEIVING','Nhận 2','RECEIVING',true)"), {'id':second_location,'wh':trace.warehouse})
        c.execute(text("INSERT INTO wms.serial(id,product_id,code) VALUES (:id,:product,'SER-COMPETE')"), {'id':serial,'product':product['id']})
        owned = resolve_stock_identity(c,product_id=UUID(product['id']),owner_id=COMPANY_OWNER,warehouse_id=trace.warehouse,business_date=date(2026,10,2),serial_id=serial)
        consigned = resolve_stock_identity(c,product_id=UUID(product['id']),owner_id=UUID(owner['id']),consignment_id=UUID(agreement['id']),warehouse_id=trace.warehouse,business_date=date(2026,10,2),serial_id=serial)
    gate = Barrier(2)
    def store(item):
        gate.wait(timeout=5)
        try:
            with trace.engine.begin() as c:
                c.execute(text('INSERT INTO wms.stock_balance VALUES (:id,:item,:location,1,0,1)'), {'id':uuid4(),'item':item,'location':trace.location if item==owned else second_location})
            return 'stored'
        except IntegrityError:
            return 'rejected'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(store,[owned,consigned])) == ['rejected','stored']
    with trace.engine.connect() as c:
        assert c.execute(text('SELECT sum(on_hand) FROM wms.stock_balance')).scalar_one() == 1


def test_reservations_do_not_cross_owner_and_consignment_outbound_is_blocked(trace):
    owner, agreement = trace.consignment()
    product = trace.product()
    owned = trace.receipt(product,qty=10)
    consigned = trace.receipt(product,qty=5,owner=owner['id'],agreement=agreement['id'])
    for line in [owned['line'], consigned['line']]:
        with pytest.raises(IntegrityError), trace.engine.begin() as c:
            c.execute(text('INSERT INTO wms.reservation VALUES (:id,:line,:item,:location,1,0,0,NULL,:user)'),
                      {'id':uuid4(),'line':line,'item':consigned['item'],'location':trace.location,'user':trace.user})
    with pytest.raises(IntegrityError), trace.engine.begin() as c:
        txn = uuid4()
        c.execute(text("INSERT INTO wms.inventory_transaction(id,document_id,execution_key,operation,business_date,posted_at,posted_by) VALUES (:id,:doc,:key,'ISSUE',:day,now(),:user)"),
                  {'id':txn,'doc':consigned['document'],'key':uuid4(),'day':date(2026,10,2),'user':trace.user})
        c.execute(text('INSERT INTO wms.stock_move VALUES (:id,:txn,:line,:item,:source,:dest,1,:unit,NULL)'),
                  {'id':uuid4(),'txn':txn,'line':consigned['line'],'item':consigned['item'],'source':trace.location,'dest':trace.external,'unit':product['base_uom_id']})
    with trace.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.inventory_transaction WHERE operation='ISSUE'")).scalar_one() == 0


def test_warranty_unknown_valid_expired_future_and_partial_evidence(trace):
    row = trace.receipt(serial_code='00001234')
    initial = trace.read(row)
    assert initial.status_code == 200, initial.text
    assert initial.json()['status'] == 'UNKNOWN' and initial.json()['version'] == 0
    assert initial.json()['received_on'] == '2026-10-02'
    assert initial.json()['supplier_partner_id'] == trace.supplier
    cases=[
        ({'starts_on':'2026-10-01','ends_on':'2026-10-02','evidence_ref':'Phiếu BH-01'},'VALID'),
        ({'starts_on':'2025-01-01','ends_on':'2026-10-01','evidence_ref':'Phiếu BH-02'},'EXPIRED'),
        ({'starts_on':'2027-01-01','ends_on':'2028-01-01','evidence_ref':'Phiếu BH-03'},'UNKNOWN'),
        ({'starts_on':'2026-01-01','ends_on':'2027-01-01'},'UNKNOWN'),
        ({'evidence_ref':'Phiếu thiếu mốc'},'UNKNOWN')]
    for version,(body,status) in enumerate(cases):
        r = trace.record(row,version=version,**body)
        assert r.status_code == 201,r.text
        view = trace.read(row).json()
        assert view['status'] == status and view['version'] == version+1
        assert 'price' not in str(view) and 'amount' not in str(view)
    results = trace.client.get('/api/v1/serials/lookup',params={'warehouse_id':trace.warehouse,'code':'00001234'},headers=trace.headers)
    assert results.status_code == 200 and results.json()[0]['serial_code'] == '00001234'
    assert trace.client.get('/api/v1/serials/lookup',params={'warehouse_id':trace.warehouse,'code':'1234'},headers=trace.headers).json() == []


def test_warranty_uses_server_business_timezone_not_client_date(trace):
    row = trace.receipt(serial_code='TZ-01')
    assert trace.record(row,starts_on='2026-01-01',ends_on='2026-10-02',evidence_ref='Chứng cứ TZ').status_code == 201
    assert trace.read(row).json()['status'] == 'VALID'
    trace.iam.advance(seconds=4*3600)  # UTC still Oct 2; Asia/Ho_Chi_Minh is already Oct 3.
    trace.headers = trace.iam.headers(trace.iam.login('keeper'))
    result=trace.read(row).json()
    assert result['as_of']=='2026-10-03' and result['status']=='EXPIRED'


def test_warranty_source_permissions_assignment_and_replay_revocation(trace):
    row = trace.receipt(serial_code='SCOPE-01')
    user,_ = trace.iam.user('receiver')
    grant=trace.iam.grant(user,'RECEIVER',trace.warehouse)
    headers=trace.iam.headers(trace.iam.login('receiver'))
    other = trace.iam.warehouse('WARRANTY-OTHER')
    trace.iam.grant(user,'WAREHOUSE_MANAGER',other)
    assert trace.read(row,headers,warehouse=other).status_code == 404
    assert trace.read(row,headers).status_code == 404
    with trace.engine.begin() as c:
        c.execute(text('INSERT INTO wms.document_assignment VALUES (:id,:doc,:user,:by)'),{'id':uuid4(),'doc':row['document'],'user':user,'by':trace.user})
    assert trace.read(row,headers).status_code == 200
    assert trace.record(row,headers=headers).status_code == 403
    with trace.engine.begin() as c:
        c.execute(text('UPDATE wms.user_role_grant SET revoked_at=now() WHERE id=:id'),{'id':grant})
    assert trace.read(row,headers).status_code == 404
    key=uuid4()
    saved=trace.record(row,key=key,evidence_ref='Chứng cứ quyền')
    assert saved.status_code==201
    assert trace.record(row,key=key,evidence_ref='Chứng cứ quyền').json()==saved.json()
    assert trace.record(row,key=key,evidence_ref='Khác chứng cứ').json()['code']=='IDEMPOTENCY_MISMATCH'
    with trace.engine.begin() as c:
        c.execute(text('UPDATE wms.user_role_grant SET revoked_at=now() WHERE id=:id'),{'id':trace.grant})
    assert trace.record(row,key=key,evidence_ref='Chứng cứ quyền').status_code==404


def test_warranty_concurrency_and_failpoint_preserve_history(trace,monkeypatch):
    row=trace.receipt(serial_code='CONCURRENT-01')
    gate=Barrier(2)
    def save(_):
        gate.wait(timeout=5)
        return trace.record(row,evidence_ref='Chứng cứ cạnh tranh')
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(save,range(2)))
    assert sorted(r.status_code for r in responses)==[201,409]
    service=trace.client.app.state.traceability
    original=service.effects
    def fail(*args):
        original(*args)
        raise RuntimeError('fixture failure after audit/outbox')
    monkeypatch.setattr(service,'effects',fail)
    assert trace.record(row,version=1,evidence_ref='Chứng cứ rollback').status_code==500
    assert trace.read(row).json()['version']==1
    with trace.engine.connect() as c:
        assert c.execute(text('SELECT count(*) FROM wms.serial_warranty_record')).scalar_one()==1
        assert c.execute(text("SELECT count(*) FROM wms.outbox_event WHERE event_type='serial.warranty.recorded.v1'")).scalar_one()==1
    with pytest.raises(DatabaseError), trace.engine.begin() as c:
        c.execute(text("UPDATE wms.serial_warranty_record SET evidence_ref='Rewritten'"))


@pytest.mark.parametrize('source_disappears_at', [2, 3])
def test_warranty_source_lost_after_authorization_is_a_conflict(trace, monkeypatch, source_disappears_at):
    row = trace.receipt(serial_code='SOURCE-CHANGED')
    service = trace.client.app.state.traceability
    original = service.receipt
    calls = 0

    def changing_source(*args, **kwargs):
        nonlocal calls
        calls += 1
        # Simulate reversal between authorization and either pre-lock or post-lock validation.
        return None if calls >= source_disappears_at else original(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(service, 'receipt', changing_source)
        response = trace.record(row, evidence_ref='Nguồn thay đổi trong lúc lưu')
    assert response.status_code == 409
    assert response.json()['code'] == 'INVALID_SOURCE'
    assert trace.read(row).json()['version'] == 0
    with trace.engine.connect() as c:
        assert c.execute(text('SELECT count(*) FROM wms.serial_warranty_record')).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM wms.outbox_event WHERE event_type='serial.warranty.recorded.v1'")).scalar_one() == 0


def test_wrong_serial_or_unposted_receipt_cannot_supply_warranty(trace):
    one=trace.receipt(serial_code='ONE')
    two=trace.receipt(serial_code='TWO')
    assert trace.record(one,receipt_move_id=str(two['move'])).status_code==404
    assert trace.record(one,receipt_move_id=str(uuid4())).status_code==404
    assert trace.record(one,starts_on='2027-01-01',ends_on='2026-01-01').status_code==422
    with pytest.raises(IntegrityError), trace.engine.begin() as c:
        c.execute(text("""INSERT INTO wms.serial_warranty_record
            (id,serial_id,receipt_move_id,revision,recorded_by,recorded_at,reason)
            VALUES (:id,:serial,:move,1,:user,now(),'Fixture wrong source')"""),
                  {'id':uuid4(),'serial':one['serial'],'move':two['move'],'user':trace.user})


def test_two_connections_resolve_same_owner_dimensions_to_one_identity(trace):
    product=trace.product()
    gate=Barrier(2)
    def resolve(_):
        gate.wait(timeout=5)
        with trace.engine.begin() as c:
            return resolve_stock_identity(c,product_id=UUID(product['id']),owner_id=COMPANY_OWNER,
                                          warehouse_id=trace.warehouse,business_date=date(2026,10,2))
    with ThreadPoolExecutor(max_workers=2) as pool:
        identities=list(pool.map(resolve,range(2)))
    assert identities[0]==identities[1]
    with trace.engine.connect() as c:
        assert c.execute(text('SELECT count(*) FROM wms.stock_item')).scalar_one()==1


@pytest.mark.gui
def test_serial_desktop_shows_three_statuses_and_clears_on_logout(trace):
    import socket
    import threading
    import time
    import tkinter as tk

    import uvicorn

    from apps.desktop.api.client import DesktopSettings
    from apps.desktop.views.shell import DesktopShell

    valid = trace.receipt(serial_code='000-SHARED')
    expired = trace.receipt(serial_code='000-SHARED')
    trace.receipt(serial_code='000-SHARED')
    assert trace.record(valid,starts_on='2026-01-01',ends_on='2027-01-01',evidence_ref='Phiếu BH còn hạn').status_code == 201
    assert trace.record(expired,starts_on='2025-01-01',ends_on='2026-01-01',evidence_ref='Phiếu BH đã hết').status_code == 201
    sock = socket.socket()
    sock.bind(('127.0.0.1',0))
    server = uvicorn.Server(uvicorn.Config(trace.client.app,access_log=False,log_level='warning'))
    thread = threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True)
    thread.start()
    shell = None
    try:
        deadline = time.monotonic()+5
        while not server.started and time.monotonic()<deadline:
            time.sleep(.01)
        assert server.started
        root = tk.Tk()
        shell = DesktopShell(root,DesktopSettings(api_url=f'http://127.0.0.1:{sock.getsockname()[1]}/api/v1'))
        def wait(predicate):
            deadline = time.monotonic()+5
            while not predicate() and time.monotonic()<deadline:
                root.update()
                time.sleep(.01)
            assert predicate()
        session, view = shell.session_view, shell.serial_view
        session.username.set('keeper')
        session.password.set('Test-only-password-2026!')
        session.login()
        wait(lambda: len(view.warehouses)==1)
        view.code.set('000-SHARED')
        view.search()
        wait(lambda: len(view.rows)==3)
        assert {r.status for r in view.rows.values()}=={'VALID','EXPIRED','UNKNOWN'}
        statuses={view.table.item(i,'values')[2] for i in view.table.get_children()}
        assert statuses=={'Còn bảo hành','Hết bảo hành','Chưa xác định'}
        assert 'Nhà cung cấp giả' in view.details.get()
        session.logout()
        assert view.rows=={} and view.details.get()=='' and view.code.get()==''
        wait(lambda: session.status.get()=='Đã đăng xuất.')
    finally:
        if shell:
            shell.close()
            shell.finish()
        server.should_exit=True
        thread.join(timeout=5)
        sock.close()
        assert not thread.is_alive()
