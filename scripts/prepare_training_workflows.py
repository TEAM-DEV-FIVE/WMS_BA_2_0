"""Linked training workflows via service APIs, never direct inventory writes."""
import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

from packages.contracts.traceability import COMPANY_OWNER
from scripts.prepare_training_quality import maintenance

REASON = 'Thực hành nghiệp vụ InternTechLead; không phải chứng từ giao dịch thực tế'


def seed_workflows(engine, settings, username='kien', *, prefix='DEMO-', reason=REASON):
    if not engine.url.database.startswith(('wms_demo_', 'wms_test_', 'wms_dataset_')):
        raise ValueError('Only demo/test databases are allowed')
    with engine.connect() as c:
        if c.execute(text("SELECT count(*) FROM wms.audit_event WHERE action='training.workflows.started'")).scalar_one():
            raise ValueError('A preparation already exists; inspect its report before retrying')
        actor = c.execute(text('SELECT id FROM wms.app_user WHERE username=:name AND is_active'), {'name': username}).scalar_one()
    summary = []
    with maintenance(engine, settings, username, workflows=True, warehouse_prefix=prefix) as (request, tokens, warehouses):
        loader, reviewer, counter1, counter2, director = tokens
        ids = [request('GET', 'auth/me', token=t)['id'] for t in tokens]
        day = str(date.today())

        def get(path, token=loader):
            return request('GET', path, token=token)

        def post(path, body, token=loader, expected=200):
            return request('POST', path, body, token, expected)

        def create(path, **body):
            return post(path, dict(reason=reason, **body), expected=201)

        def submit(doc):
            return post('documents/'+doc['id']+'/submit', dict(expected_version=doc['version'], reason=reason))

        def approve(doc):
            submitted = submit(doc)
            return post('approval-requests/'+submitted['approval_request_id']+'/decide',
                        dict(expected_version=submitted['version'], decision='APPROVE', reason=reason), reviewer)

        def posted(route, doc, token=loader, **extra):
            return post(route+'/'+doc['id']+'/post', dict(expected_version=doc['version'], execution_key=str(uuid4()), reason=reason, **extra), token)

        with engine.begin() as c:
            c.execute(text("""INSERT INTO wms.audit_event(id,actor_id,action,entity_type,entity_id,request_id,occurred_at,after_data,reason)
                VALUES (:id,:actor,'training.workflows.started','app_user',:actor,:request,now(),'{}',:reason)"""),
                dict(id=uuid4(), actor=actor, request=uuid4(), reason=reason))
        partner = create('master/partners', code='DISTRIBUTION' if prefix != 'DEMO-' else 'ITL-PRACTICE-PARTNER', name='Đối tác phân phối' if prefix != 'DEMO-' else 'Đối tác thực hành InternTechLead', is_supplier=True, is_customer=True)
        owner = create('master/stock-owners', code='CONSIGNOR' if prefix != 'DEMO-' else 'ITL-PRACTICE-OWNER', name='Chủ hàng ký gửi' if prefix != 'DEMO-' else 'Chủ hàng thực hành InternTechLead', partner_id=partner['id'])
        with engine.connect() as c:
            products = [dict(r) for r in c.execute(text("""SELECT p.id,p.sku,u.id AS unit FROM wms.product p JOIN wms.product_uom u ON u.product_id=p.id AND u.uom_id=p.base_uom_id AND u.is_active
                WHERE p.sku LIKE :prefix AND p.tracking='NONE' ORDER BY p.sku LIMIT 5"""), {"prefix":prefix+"%"}).mappings()]
        if len(products) != 5 or len(warehouses) != 3:
            raise ValueError('Training catalog and three warehouses are required')
        for index, warehouse in enumerate(warehouses):
            wid, suffix = str(warehouse['id']), warehouse['code'].removeprefix(prefix)
            record = {'warehouse': warehouse['code']}
            with engine.connect() as c:
                locations = {r['kind']: str(r['id']) for r in c.execute(text('SELECT id,kind FROM wms.location WHERE warehouse_id=:id AND is_active ORDER BY code DESC'), {'id': wid}).mappings()}
                stock = {str(r['product_id']): str(r['id']) for r in c.execute(text('SELECT id,product_id FROM wms.stock_item WHERE owner_id=:owner AND consignment_id IS NULL AND lot_id IS NULL AND serial_id IS NULL'), {'owner': COMPANY_OWNER}).mappings()}
            with engine.connect() as c:
                source_bins = {str(r['product_id']):str(r['location_id']) for r in c.execute(text("""SELECT s.product_id,b.location_id FROM wms.stock_balance b
                    JOIN wms.stock_item s ON s.id=b.stock_item_id JOIN wms.location l ON l.id=b.location_id
                    WHERE l.warehouse_id=:w AND l.kind='STORAGE' AND b.on_hand-b.reserved>=10 AND s.owner_id=:owner"""), {'w':wid,'owner':COMPANY_OWNER}).mappings()}
            storage, receiving = locations['STORAGE'], locations['RECEIVING']
            with engine.connect() as c:
                rack = str(c.execute(text('SELECT parent_id FROM wms.location WHERE id=:id'), {'id':storage}).scalar_one())
            bin2 = create('master/locations', code=('COUNT-' if prefix != 'DEMO-' else 'ITL-PRACTICE-')+suffix, name='Vị trí kiểm kê '+suffix, warehouse_id=wid, parent_id=rack, kind='STORAGE')['id']
            contract = create('master/consignment-agreements', code='ITL-CG-'+suffix, owner_id=owner['id'], warehouse_id=wid,
                              valid_from=day, valid_until=str(date.today()+timedelta(days=365)), source_ref=reason)
            cg = create('consignment-receipts', warehouse_id=wid, batch_key=str(uuid4()), business_date=day, delivery_reference=reason,
                        lines=[dict(product_id=str(p['id']), quantity_base='10', owner_id=owner['id'], consignment_id=contract['id'], destination_location_id=receiving) for p in products])
            record['consignment'] = posted('consignment-receipts', approve(cg))['id']
            putaway_lines = []
            for source in get('quality/sources?warehouse_id='+wid+'&limit=200')['items']:
                if source['tracking'] != 'NONE' or source['owner_id'] != str(COMPANY_OWNER):
                    continue
                history = get('quality/sources/'+source['id'])
                decision = next((q for q in history['items'] if q['result']=='ACCEPT' and Decimal(q['remaining_base'])>=2), None)
                if decision:
                    putaway_lines.append(dict(stock_item_id=source['stock_item_id'], source_location_id=source['source_location_id'],
                                              destination_location_id=storage, quality_decision_id=decision['id'], quantity_base='2'))
                if len(putaway_lines) == 5:
                    break
            if len(putaway_lines) != 5:
                raise ValueError('Five accepted quality sources are required')
            record['putaway'] = posted('moves', approve(create('moves', warehouse_id=wid, business_date=day, lines=putaway_lines)))['id']
            # Physical move creates a small isolated count scope; no other bin is frozen.
            move = create('moves', warehouse_id=wid, business_date=day,
                          lines=[dict(stock_item_id=stock[str(p['id'])], source_location_id=source_bins[str(p['id'])], destination_location_id=bin2, quantity_base='5') for p in products])
            record['move'] = posted('moves', approve(move))['id']
            # A separate reversible movement gives a complete reversal example.
            revmove = create('moves', warehouse_id=wid, business_date=day,
                             lines=[dict(stock_item_id=stock[str(products[0]['id'])], source_location_id=source_bins[str(products[0]['id'])], destination_location_id=bin2, quantity_base='1')])
            tx = posted('moves', approve(revmove))['transaction_id']
            preview = get('transactions/'+tx+'/reversal-preview?business_date='+day)
            reversal = create('reversals', source_transaction_id=tx, source_version=preview['source']['source_version'], business_date=day)
            record['reversal'] = posted('reversals', approve(reversal), reviewer)['id']
            count = create('counts', warehouse_id=wid, business_date=day, scope=[dict(location_id=bin2,user_ids=[ids[2],ids[3]])])
            def count_action(action, token=loader, **extra):
                current = get('counts/'+count['id'])
                return post('counts/'+count['id']+'/'+action, dict(expected_version=current['version'], reason=reason, **extra), token)
            count_action('freeze')
            for line in get('counts/'+count['id'])['lines']:
                for round_no, token in enumerate((counter1,counter2), 1):
                    count_action('observe', token, line_id=line['id'], round_no=round_no, quantity='4', scan_event_key=str(uuid4()))
            count_action('submit')
            count_action('decide', reviewer, decision='APPROVE')
            count_action('decide', director, decision='APPROVE')
            count_action('post', reviewer, execution_key=str(uuid4()))
            record['count'] = count['id']
            # Purchasing, approved sale, and a submitted purchase for the inbox.
            order_body = dict(warehouse_id=wid, partner_id=partner['id'], business_date=day,
                              lines=[dict(product_id=str(p['id']), product_uom_id=str(p['unit']), quantity='10', owner_id=str(COMPANY_OWNER)) for p in products])
            record['pending_purchase'] = create('purchase-orders', **order_body)['id']
            pending = create('purchase-orders', **order_body)
            submit(pending)
            record['approval'] = pending['id']
            sale = approve(create('sales-orders', **order_body))
            sale_detail = get('sales-orders/'+sale['id'])
            issue = approve(create('issues', source_order_id=sale['id'], business_date=day,
                                   lines=[dict(source_line_id=line['id'], quantity_base='5') for line in sale_detail['lines']]))
            issue_detail = get('issues/'+issue['id'])
            allocations = []
            for line in issue_detail['lines']:
                proposal = get(f"issues/{issue['id']}/reservation-plan?document_line_id={line['id']}&quantity_base=5")
                allocations += [{key: r[key] for key in ('document_line_id','stock_item_id','location_id','quantity_base')} for r in proposal['lines']]
            post('issues/'+issue['id']+'/reservations/reserve', dict(expected_version=issue['version'], reason=reason, lines=allocations))
            work = get('fulfillment/'+issue['id'])
            for reservation in work['reservations']:
                current = get('fulfillment/'+issue['id'])
                created = post('fulfillment/'+issue['id']+'/picks', dict(expected_version=current['version'], reason=reason,
                               reservation_id=reservation['id'], assigned_to=ids[0], quantity_base=reservation['remaining_base']), expected=201)
                task = next(t for t in get('fulfillment/'+issue['id'])['tasks'] if t['id']==created['entity_id'])
                post('fulfillment/'+issue['id']+'/picks/'+task['id']+'/confirm', dict(expected_version=created['version'], entity_version=task['version'],
                     reason=reason, quantity_base=reservation['remaining_base'], location_code=reservation['location_code'], item_code=reservation['sku']))
            current = get('fulfillment/'+issue['id'])
            package = post('fulfillment/'+issue['id']+'/packages', dict(expected_version=current['version'], reason=reason, code='ITL-PACK-'+suffix,
                           lines=[dict(pick_task_id=t['id'], quantity_base=t['unpacked_base']) for t in current['tasks']]), expected=201)
            sealed = post('fulfillment/'+issue['id']+'/packages/'+package['entity_id']+'/seal',
                          dict(expected_version=package['version'], entity_version=package['entity_version'], reason=reason))
            current = get('issues/'+issue['id'])
            record['issue'] = posted('issues', sealed, lines=[dict(reservation_id=r['id'], quantity_base=r['remaining_base']) for r in current['reservations']])['id']
            # Keep a second approved issue with reservations, ready for the user's next steps.
            held = approve(create('issues', source_order_id=sale['id'], business_date=day,
                                  lines=[dict(source_line_id=line['id'], quantity_base='2') for line in sale_detail['lines']]))
            detail = get('issues/'+held['id'])
            allocation = []
            for line in detail['lines']:
                proposal = get(f"issues/{held['id']}/reservation-plan?document_line_id={line['id']}&quantity_base=2")
                allocation += [{key:r[key] for key in ('document_line_id','stock_item_id','location_id','quantity_base')} for r in proposal['lines']]
            held = post('issues/'+held['id']+'/reservations/reserve', dict(expected_version=held['version'], reason=reason, lines=allocation))
            current = get('fulfillment/'+held['id'])
            post('fulfillment/'+held['id']+'/picks', dict(expected_version=current['version'], reason=reason, reservation_id=current['reservations'][0]['id'],
                 assigned_to=str(actor), quantity_base=current['reservations'][0]['remaining_base']), expected=201)
            record['ready_issue'] = held['id']
            for kind, source_document, location in [('CUSTOMER_RETURN', issue['id'], locations['QUARANTINE']), ('SUPPLIER_RETURN', None, receiving)]:
                sources = get('returns/sources?warehouse_id='+wid+'&kind='+kind+'&limit=200')['items']
                source = next(r for r in sources if r['tracking']=='NONE' and r['returnable'] and (source_document is None or r['document_id']==source_document))
                ret = create('returns', kind=kind, source_document_id=source['document_id'], business_date=day,
                             lines=[dict(source_move_id=source['id'], location_id=location, quantity_base='1')])
                record[kind.lower()] = posted('returns', approve(ret))['id']
            destination = str(warehouses[(index+1)%3]['id'])
            tr = create('transfers', warehouse_id=wid, destination_warehouse_id=destination, business_date=day,
                        lines=[dict(stock_item_id=stock[str(products[-1]['id'])], source_location_id=source_bins[str(products[-1]['id'])], quantity_base='2')])
            tr = post('documents/'+tr['id']+'/assignments', dict(expected_version=tr['version'], reason=reason, user_ids=[ids[0], str(actor)]))
            tr = approve(tr)
            tr = post('transfers/'+tr['id']+'/dispatch', dict(expected_version=tr['version'], execution_key=str(uuid4()), evidence_ref=reason, reason=reason))
            detail = get('transfers/'+tr['id'])
            with engine.connect() as c:
                dest = str(c.execute(text("SELECT id FROM wms.location WHERE warehouse_id=:id AND kind='RECEIVING' ORDER BY code LIMIT 1"), {'id':destination}).scalar_one())
            post('transfers/'+tr['id']+'/receive', dict(expected_version=tr['version'], execution_key=str(uuid4()), business_date=day, reason=reason, evidence_ref=reason,
                 lines=[dict(dispatch_move_id=detail['sources'][0]['dispatch_move_id'], destination_location_id=dest, quantity_base='1')]))
            record['transfer'] = tr['id']
            # Evidence is explicitly synthetic and linked to the actual training receipt.
            with engine.connect() as c:
                serials = list(c.execute(text("""SELECT s.serial_id,m.id FROM wms.stock_move m JOIN wms.stock_item s ON s.id=m.stock_item_id
                    JOIN wms.inventory_transaction t ON t.id=m.transaction_id JOIN wms.document d ON d.id=t.document_id
                    WHERE d.warehouse_id=:w AND d.kind='RECEIPT' AND t.operation='RECEIVE' AND s.serial_id IS NOT NULL ORDER BY s.serial_id LIMIT 3"""), {'w':wid}).mappings())
            for serial in serials:
                post('serials/'+str(serial['serial_id'])+'/warranty-records', dict(expected_version=0, receipt_move_id=str(serial['id']), starts_on=day,
                     ends_on=str(date.today()+timedelta(days=365)), evidence_ref=reason, reason=reason), expected=201)
            record['warranties'] = len(serials)
            summary.append(record)
        for name in ['reconcile.sql','reconcile_ownership.sql','reconcile_fulfillment.sql','reconcile_transfers.sql']:
            with engine.connect() as c, c.connection.driver_connection.cursor() as cursor:
                cursor.execute((Path(__file__).resolve().parents[1]/'02_CSDL'/name).read_text())
                while True:
                    if cursor.description and cursor.fetchall():
                        raise RuntimeError('Reconciliation failed: '+name)
                    if not cursor.nextset():
                        break
        with engine.begin() as c:
            c.execute(text("""INSERT INTO wms.audit_event(id,actor_id,action,entity_type,entity_id,request_id,occurred_at,after_data,reason)
                VALUES (:id,:actor,'training.workflows.completed','app_user',:actor,:request,now(),CAST(:data AS jsonb),:reason)"""),
                dict(id=uuid4(),actor=actor,request=uuid4(),data=json.dumps(summary),reason=reason))
    return summary
