-- Read-only B11 checks. Every result set must be empty; run with generic reconcile.sql.
-- R05: each source dispatch is consumed only by linked arrivals/losses, never by a note.
WITH sources AS (
 SELECT m.id,m.quantity_base,coalesce(sum(child.quantity_base),0) AS consumed
 FROM wms.stock_move m JOIN wms.inventory_transaction t ON t.id=m.transaction_id AND t.operation='DISPATCH'
 JOIN wms.document d ON d.id=t.document_id AND d.kind='TRANSFER'
 LEFT JOIN wms.transfer_move link ON link.dispatch_move_id=m.id
 LEFT JOIN wms.stock_move child ON child.id=link.move_id
   AND NOT EXISTS(SELECT 1 FROM wms.stock_move r WHERE r.reverses_move_id=child.id)
 WHERE NOT EXISTS(SELECT 1 FROM wms.stock_move r WHERE r.reverses_move_id=m.id)
 GROUP BY m.id,m.quantity_base
)
SELECT * FROM sources WHERE consumed>quantity_base;

-- Transit is private to one document; its balance equals dispatched minus received/lost.
WITH quantities AS (
 SELECT t.document_id,m.stock_item_id,
 CASE WHEN EXISTS(SELECT 1 FROM wms.stock_move r WHERE r.reverses_move_id=m.id) THEN 0 ELSE m.quantity_base END - coalesce((
   SELECT sum(child.quantity_base) FROM wms.transfer_move link JOIN wms.stock_move child ON child.id=link.move_id
   WHERE link.dispatch_move_id=m.id
   AND NOT EXISTS(SELECT 1 FROM wms.stock_move r WHERE r.reverses_move_id=child.id)),0) AS remaining
 FROM wms.stock_move m JOIN wms.inventory_transaction t ON t.id=m.transaction_id AND t.operation='DISPATCH'
 JOIN wms.document d ON d.id=t.document_id AND d.kind='TRANSFER'
), expected AS (
 SELECT document_id,stock_item_id,sum(remaining) AS quantity FROM quantities GROUP BY document_id,stock_item_id
)
SELECT d.id,e.stock_item_id,e.quantity,b.on_hand FROM expected e JOIN wms.document d ON d.id=e.document_id
LEFT JOIN wms.stock_balance b ON b.location_id=d.transit_location_id AND b.stock_item_id=e.stock_item_id
WHERE coalesce(b.on_hand,0)<>e.quantity;

-- Linked source identity and route must remain intact, including loss adjustments.
SELECT child.id FROM wms.transfer_move link JOIN wms.stock_move child ON child.id=link.move_id
JOIN wms.stock_move source ON source.id=link.dispatch_move_id
JOIN wms.inventory_transaction st ON st.id=source.transaction_id
JOIN wms.inventory_transaction ct ON ct.id=child.transaction_id
WHERE source.stock_item_id<>child.stock_item_id OR source.destination_location_id<>child.source_location_id
 OR st.operation<>'DISPATCH'
 OR (link.disposition IN ('GOOD','DAMAGED') AND (ct.operation<>'ARRIVE' OR ct.document_id<>st.document_id))
 OR (link.disposition='LOSS' AND (ct.operation<>'ADJUST' OR NOT EXISTS(
   SELECT 1 FROM wms.transfer_adjustment a WHERE a.document_id=ct.document_id AND a.source_transfer_id=st.document_id)));
