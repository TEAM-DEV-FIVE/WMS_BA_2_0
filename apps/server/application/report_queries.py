"""Read-only report SQL. Every quantity retains PostgreSQL numeric precision.

The boundary is an explicit set of leaf locations, never an inferred hierarchy.
Ledger reports include inverse moves; fulfillment reports net cancelled originals.
"""

COMMON = """
WITH boundary AS (SELECT id FROM wms.location WHERE warehouse_id=:warehouse
  AND kind IN ('STORAGE','RECEIVING','QUARANTINE','SHIPPING')
  AND (cardinality(CAST(:locations AS uuid[]))=0 OR id=ANY(CAST(:locations AS uuid[])))),
items AS (SELECT i.*,p.sku,p.name AS product_name,p.tracking,p.expiry_required,
  p.is_active AS product_active,u.code AS base_uom,u.is_active AS unit_active,
  o.code AS owner_code,o.kind AS owner_kind,lot.code AS lot_code,lot.expires_on,
  s.code AS serial_code FROM wms.stock_item i JOIN wms.product p ON p.id=i.product_id
  JOIN wms.uom u ON u.id=p.base_uom_id JOIN wms.stock_owner o ON o.id=i.owner_id
  LEFT JOIN wms.lot lot ON lot.id=i.lot_id LEFT JOIN wms.serial s ON s.id=i.serial_id
  WHERE (CAST(:owner AS uuid) IS NULL OR i.owner_id=:owner)
    AND (CAST(:product AS uuid) IS NULL OR i.product_id=:product)),
moves AS (SELECT m.*,t.posted_at,t.business_date,t.operation,t.document_id,t.posted_by,
  t.reverses_transaction_id,t.id AS transaction_sort,
  m.source_location_id IN (SELECT id FROM boundary) AS source_inside,
  m.destination_location_id IN (SELECT id FROM boundary) AS destination_inside
  FROM wms.stock_move m JOIN wms.inventory_transaction t ON t.id=m.transaction_id
  WHERE (m.source_location_id IN (SELECT id FROM boundary)
      OR m.destination_location_id IN (SELECT id FROM boundary))
    AND (CAST(:business_from AS date) IS NULL OR t.business_date>=:business_from)
    AND (CAST(:business_to AS date) IS NULL OR t.business_date<=:business_to)
    AND (CAST(:posted_from AS timestamptz) IS NULL OR t.posted_at>=:posted_from)
    AND (CAST(:posted_to AS timestamptz) IS NULL OR t.posted_at<=:posted_to))
"""

DIMENSIONS = "i.product_id,i.sku,i.product_name,i.base_uom,i.owner_id,i.owner_code,i.owner_kind,i.consignment_id,i.lot_code,i.serial_code"

STOCK = """, balances AS (
 SELECT b.*,l.code AS location_code,l.kind AS location_kind,
 CASE WHEN l.kind='STORAGE' AND l.is_active AND i.product_active AND i.unit_active
   AND i.owner_kind='COMPANY' AND i.consignment_id IS NULL
   AND (i.expires_on IS NULL OR i.expires_on>=:today)
   AND (NOT i.expiry_required OR i.expires_on IS NOT NULL)
   AND NOT EXISTS(SELECT 1 FROM wms.count_location_lock cl WHERE cl.location_id=l.id AND cl.released_at IS NULL)
   AND (i.tracking<>'SERIAL' OR (b.on_hand=1 AND EXISTS(
      SELECT 1 FROM wms.serial_position sp WHERE sp.serial_id=i.serial_id AND sp.location_id=l.id)))
   THEN b.on_hand ELSE 0 END AS eligible,
 COALESCE((SELECT sum(r.quantity-r.consumed-r.released) FROM wms.reservation r
   WHERE r.stock_item_id=b.stock_item_id AND r.location_id=b.location_id),0) AS remaining_reserved
 FROM wms.stock_balance b JOIN items i ON i.id=b.stock_item_id JOIN wms.location l ON l.id=b.location_id
 WHERE l.id IN (SELECT id FROM boundary) OR
 (cardinality(CAST(:locations AS uuid[]))=0 AND l.kind='TRANSIT' AND EXISTS(
   SELECT 1 FROM wms.document d WHERE d.transit_location_id=l.id AND d.kind='TRANSFER'
   AND :warehouse IN (d.warehouse_id,d.destination_warehouse_id)
   AND d.warehouse_id=ANY(CAST(:warehouses AS uuid[]))
   AND d.destination_warehouse_id=ANY(CAST(:warehouses AS uuid[])))))
"""

QUERIES = {
    "R01": COMMON
    + STOCK
    + f"""
SELECT b.id,{DIMENSIONS},b.location_id,b.location_code,b.location_kind,
 CASE WHEN b.location_kind='TRANSIT' THEN 0 ELSE b.on_hand END AS physical,
 CASE WHEN b.location_kind='TRANSIT' THEN b.on_hand ELSE 0 END AS transit,
 b.eligible,b.remaining_reserved AS reserved,b.eligible-b.remaining_reserved AS available,
 b.reserved AS balance_reserved,b.reserved=b.remaining_reserved AS reservation_reconciled
FROM balances b JOIN items i ON i.id=b.stock_item_id ORDER BY i.sku,b.location_code,i.owner_code,b.id
""",
    "R02": COMMON
    + """, history AS (
SELECT m.*,t.posted_at,t.business_date,
 m.source_location_id IN (SELECT id FROM boundary) AS source_inside,
 m.destination_location_id IN (SELECT id FROM boundary) AS destination_inside,
 (CAST(:business_from AS date) IS NULL OR t.business_date>=:business_from)
 AND (CAST(:posted_from AS timestamptz) IS NULL OR t.posted_at>=:posted_from) AS in_window
FROM wms.stock_move m JOIN wms.inventory_transaction t ON t.id=m.transaction_id
WHERE (m.source_location_id IN (SELECT id FROM boundary) OR m.destination_location_id IN (SELECT id FROM boundary))
 AND (CAST(:business_to AS date) IS NULL OR t.business_date<=:business_to)
 AND (CAST(:posted_to AS timestamptz) IS NULL OR t.posted_at<=:posted_to))
SELECT i.product_id AS id,i.sku,i.base_uom,i.owner_id,i.owner_code,i.consignment_id,
 sum(CASE WHEN NOT m.in_window THEN (m.destination_inside::int-m.source_inside::int)*m.quantity_base ELSE 0 END) AS opening,
 sum(CASE WHEN m.in_window AND m.destination_inside AND NOT m.source_inside THEN m.quantity_base ELSE 0 END) AS inbound,
 sum(CASE WHEN m.in_window AND m.source_inside AND NOT m.destination_inside THEN m.quantity_base ELSE 0 END) AS outbound,
 sum(CASE WHEN m.in_window THEN (m.destination_inside::int-m.source_inside::int)*m.quantity_base ELSE 0 END) AS net,
 sum((m.destination_inside::int-m.source_inside::int)*m.quantity_base) AS closing
FROM history m JOIN items i ON i.id=m.stock_item_id
GROUP BY i.product_id,i.sku,i.base_uom,i.owner_id,i.owner_code,i.consignment_id
ORDER BY i.sku,i.owner_code,i.product_id,i.consignment_id
""",
    "R03": COMMON
    + f"""
SELECT m.id,m.transaction_id,m.posted_at,m.business_date,m.operation,m.document_id,m.posted_by,
 m.reverses_move_id,{DIMENSIONS},
 CASE WHEN m.source_inside THEN m.source_location_id END AS source_location_id,
 CASE WHEN m.destination_inside THEN m.destination_location_id END AS destination_location_id,
 m.source_inside,m.destination_inside,m.quantity_base
FROM moves m JOIN items i ON i.id=m.stock_item_id
ORDER BY m.posted_at,m.transaction_sort,m.id
""",
    "R04": COMMON
    + """
SELECT dl.id,d.id AS document_id,d.number,d.kind,d.business_date,p.sku,u.code AS base_uom,
 o.id AS owner_id,o.code AS owner_code,dl.consignment_id,dl.base_quantity AS requested,
 dl.closed_base_quantity AS closed,'WAREHOUSE_ORDER_LINE' AS demand_scope,
 dl.base_quantity-dl.closed_base_quantity-COALESCE(posted.quantity,0) AS open_demand,
 COALESCE(res.remaining,0) AS reserved,
 COALESCE(res.reservations,'[]'::jsonb) AS reservations
FROM wms.document_line dl JOIN wms.document d ON d.id=dl.document_id
JOIN wms.product p ON p.id=dl.product_id JOIN wms.uom u ON u.id=p.base_uom_id
JOIN wms.stock_owner o ON o.id=dl.owner_id
LEFT JOIN LATERAL (SELECT sum(m.quantity_base) AS quantity FROM wms.document_line child
 JOIN wms.stock_move m ON m.line_id=child.id JOIN wms.inventory_transaction t ON t.id=m.transaction_id
 WHERE child.source_line_id=dl.id AND t.operation=CASE WHEN d.kind='SO' THEN 'ISSUE' ELSE 'RECEIVE' END
 AND NOT EXISTS(SELECT 1 FROM wms.stock_move r WHERE r.reverses_move_id=m.id)) posted ON true
LEFT JOIN LATERAL (SELECT sum(r.quantity-r.consumed-r.released) AS remaining,
 jsonb_agg(jsonb_build_object('id',r.id,'line_id',r.line_id,'location_id',r.location_id,
 'quantity',r.quantity::text,'consumed',r.consumed::text,'released',r.released::text,
 'remaining',(r.quantity-r.consumed-r.released)::text,'expires_at',r.expires_at) ORDER BY r.id) AS reservations
 FROM wms.reservation r JOIN wms.document_line child ON child.id=r.line_id
 WHERE child.source_line_id=dl.id AND r.location_id IN (SELECT id FROM boundary)) res ON true
WHERE d.warehouse_id=:warehouse AND d.kind IN ('PO','SO') AND d.status IN ('APPROVED','PARTIAL','COMPLETED')
 AND (CAST(:owner AS uuid) IS NULL OR dl.owner_id=:owner)
 AND (CAST(:product AS uuid) IS NULL OR dl.product_id=:product)
 AND (CAST(:business_from AS date) IS NULL OR d.business_date>=:business_from)
 AND (CAST(:business_to AS date) IS NULL OR d.business_date<=:business_to)
ORDER BY p.sku,d.id,dl.id
""",
    "R05": COMMON
    + f"""
SELECT m.id,d.id AS document_id,d.number,d.warehouse_id AS source_warehouse_id,
 d.destination_warehouse_id,d.transit_location_id,m.posted_at,m.business_date,{DIMENSIONS},
 m.quantity_base AS dispatched,COALESCE(arr.good,0) AS received_good,COALESCE(arr.damaged,0) AS received_damaged,
 COALESCE(arr.loss,0) AS loss,
 m.quantity_base-COALESCE(arr.total,0) AS transit,
 tm.evidence_ref AS dispatch_evidence,COALESCE(arr.evidence,'[]'::jsonb) AS receipt_evidence,
 COALESCE(disc.evidence,'[]'::jsonb) AS discrepancy_evidence,
 COALESCE(disc.missing,0) AS reported_missing
FROM (SELECT sm.*,t.posted_at,t.business_date FROM wms.stock_move sm
 JOIN wms.inventory_transaction t ON t.id=sm.transaction_id) m
JOIN wms.transfer_move tm ON tm.move_id=m.id AND tm.disposition='DISPATCH'
JOIN wms.document_line dl ON dl.id=m.line_id JOIN wms.document d ON d.id=dl.document_id
JOIN items i ON i.id=m.stock_item_id
LEFT JOIN LATERAL (SELECT sum(a.quantity_base) AS total,
 sum(a.quantity_base) FILTER(WHERE at.disposition='GOOD') AS good,
 sum(a.quantity_base) FILTER(WHERE at.disposition='DAMAGED') AS damaged,
 sum(a.quantity_base) FILTER(WHERE at.disposition='LOSS') AS loss,
 jsonb_agg(jsonb_build_object('move_id',a.id,'disposition',at.disposition,
   'quantity',a.quantity_base::text,'evidence_ref',at.evidence_ref) ORDER BY a.id) AS evidence
 FROM wms.transfer_move at JOIN wms.stock_move a ON a.id=at.move_id
 WHERE at.dispatch_move_id=m.id AND NOT EXISTS(SELECT 1 FROM wms.stock_move r WHERE r.reverses_move_id=a.id)) arr ON true
LEFT JOIN LATERAL (SELECT sum(dc.quantity) FILTER(WHERE dc.kind='MISSING') AS missing,
 jsonb_agg(jsonb_build_object('id',dc.id,'kind',dc.kind,'quantity',dc.quantity::text,
 'evidence_ref',dc.evidence_ref,'recorded_at',dc.recorded_at) ORDER BY dc.recorded_at,dc.id) AS evidence
 FROM wms.transfer_discrepancy dc WHERE dc.dispatch_move_id=m.id) disc ON true
WHERE :warehouse IN (d.warehouse_id,d.destination_warehouse_id)
 AND d.warehouse_id=ANY(CAST(:warehouses AS uuid[])) AND d.destination_warehouse_id=ANY(CAST(:warehouses AS uuid[]))
 AND NOT EXISTS(SELECT 1 FROM wms.stock_move r WHERE r.reverses_move_id=m.id)
 AND (CAST(:business_from AS date) IS NULL OR m.business_date>=:business_from)
 AND (CAST(:business_to AS date) IS NULL OR m.business_date<=:business_to)
 AND (CAST(:posted_from AS timestamptz) IS NULL OR m.posted_at>=:posted_from)
 AND (CAST(:posted_to AS timestamptz) IS NULL OR m.posted_at<=:posted_to)
ORDER BY m.posted_at,m.id
""",
    "R06": COMMON
    + STOCK
    + f"""
SELECT b.id,{DIMENSIONS},b.location_id,b.location_code,b.location_kind,b.on_hand,i.expires_on,
 i.expires_on-CAST(:today AS date) AS days_to_expiry,
 last_move.posted_at AS last_movement_at,last_move.id AS last_move_id,
 CAST(:today AS date)-(last_move.posted_at AT TIME ZONE :timezone)::date AS movement_age_days,
 CASE WHEN last_move.id IS NULL THEN 'UNKNOWN' ELSE 'LAST_MOVEMENT_AT_LOCATION' END AS age_basis
FROM balances b JOIN items i ON i.id=b.stock_item_id
LEFT JOIN LATERAL (SELECT m.id,t.posted_at FROM wms.stock_move m
 JOIN wms.inventory_transaction t ON t.id=m.transaction_id
 WHERE m.stock_item_id=i.id AND b.location_id IN (m.source_location_id,m.destination_location_id)
 ORDER BY t.posted_at DESC,t.id DESC,m.id DESC LIMIT 1) last_move ON true
WHERE b.on_hand>0 ORDER BY i.sku,b.location_code,b.id
""",
    "R07": COMMON
    + f"""
SELECT COALESCE(cl.id,l.id) AS id,cs.id AS session_id,cs.number,cs.status,cs.business_date,cs.frozen_at,
 {DIMENSIONS},l.id AS location_id,l.code AS location_code,
 CASE WHEN cl.id IS NULL AND cs.frozen_at IS NOT NULL THEN 0 ELSE cl.snapshot_quantity END AS snapshot_quantity,
 CASE WHEN cl.id IS NULL AND cs.status='POSTED' THEN 0 ELSE cl.approved_quantity END AS approved_quantity,
 CASE WHEN cl.id IS NULL AND cs.status='POSTED' THEN 0 ELSE cl.approved_quantity-cl.snapshot_quantity END AS delta,
 COALESCE((SELECT jsonb_agg(jsonb_build_object('round_no',ob.round_no,'quantity',ob.quantity::text,
 'counted_by',ob.counted_by,'counted_at',ob.counted_at,'reason',ob.reason) ORDER BY ob.round_no)
 FROM wms.count_observation ob WHERE ob.count_line_id=cl.id),'[]'::jsonb) AS rounds,
 COALESCE((SELECT jsonb_agg(jsonb_build_object('submission_id',su.id,'session_version',su.session_version,
 'step_no',de.step_no,'decision',de.decision,'decided_by',de.decided_by,'decided_at',de.decided_at)
 ORDER BY su.created_at,su.id,de.step_no) FROM wms.count_submission su
 JOIN wms.count_decision de ON de.submission_id=su.id WHERE su.session_id=cs.id),'[]'::jsonb) AS decisions,
 cs.adjustment_document_id,
 COALESCE((SELECT jsonb_agg(jsonb_build_object('counted_by',ec.counted_by,'counted_at',ec.counted_at,'reason',ec.reason)
 ORDER BY ec.counted_at,ec.id) FROM wms.count_empty_confirmation ec
 WHERE ec.session_id=cs.id AND ec.location_id=l.id),'[]'::jsonb) AS empty_confirmations
FROM wms.count_scope scope JOIN wms.count_session cs ON cs.id=scope.session_id
JOIN wms.location l ON l.id=scope.location_id
LEFT JOIN wms.count_line cl ON cl.session_id=cs.id AND cl.location_id=l.id
LEFT JOIN items i ON i.id=cl.stock_item_id
WHERE cs.warehouse_id=:warehouse AND l.id IN (SELECT id FROM boundary)
 AND (i.id IS NOT NULL OR (cl.id IS NULL AND CAST(:product AS uuid) IS NULL AND CAST(:owner AS uuid) IS NULL))
 AND NOT EXISTS(SELECT 1 FROM wms.count_assignment ca WHERE ca.session_id=cs.id AND ca.user_id=:actor)
 AND (CAST(:business_from AS date) IS NULL OR cs.business_date>=:business_from)
 AND (CAST(:business_to AS date) IS NULL OR cs.business_date<=:business_to)
ORDER BY cs.id,l.code,i.sku,cl.id
""",
    "R08": COMMON
    + """
SELECT i.product_id AS id,i.sku,i.base_uom,i.owner_id,i.owner_code,i.consignment_id,
 count(*) AS movement_count,max(m.posted_at) AS last_posted_at,
 sum(CASE WHEN m.destination_inside AND NOT m.source_inside THEN m.quantity_base ELSE 0 END) AS inbound,
 sum(CASE WHEN m.source_inside AND NOT m.destination_inside THEN m.quantity_base ELSE 0 END) AS outbound
FROM moves m JOIN items i ON i.id=m.stock_item_id
GROUP BY i.product_id,i.sku,i.base_uom,i.owner_id,i.owner_code,i.consignment_id
ORDER BY i.sku,i.owner_code,i.product_id,i.consignment_id
""",
}
