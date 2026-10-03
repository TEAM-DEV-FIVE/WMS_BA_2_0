-- Runtime revision 006+, read-only diagnostics. Empty results mean these checks pass.
-- Original reconcile.sql remains valid: its stock_item_id already carries owner/agreement.
SET search_path TO wms, public;

WITH legs AS (
 SELECT i.owner_id,i.consignment_id,m.stock_item_id,m.destination_location_id AS location_id,m.quantity_base AS qty
 FROM stock_move m JOIN stock_item i ON i.id=m.stock_item_id
 UNION ALL
 SELECT i.owner_id,i.consignment_id,m.stock_item_id,m.source_location_id,-m.quantity_base
 FROM stock_move m JOIN stock_item i ON i.id=m.stock_item_id
), ledger AS (
 SELECT owner_id,consignment_id,stock_item_id,location_id,SUM(qty) AS qty
 FROM legs JOIN location l ON l.id=location_id
 WHERE l.kind IN ('STORAGE','RECEIVING','QUARANTINE','SHIPPING','TRANSIT')
 GROUP BY owner_id,consignment_id,stock_item_id,location_id
), balances AS (
 SELECT i.owner_id,i.consignment_id,b.* FROM stock_balance b JOIN stock_item i ON i.id=b.stock_item_id
)
SELECT COALESCE(l.stock_item_id,b.stock_item_id) AS stock_item_id,
       COALESCE(l.owner_id,b.owner_id) AS owner_id,
       COALESCE(l.location_id,b.location_id) AS location_id,l.qty,b.on_hand
FROM ledger l FULL JOIN balances b USING(stock_item_id,location_id)
WHERE COALESCE(l.qty,0)<>COALESCE(b.on_hand,0);

SELECT m.id FROM stock_move m JOIN stock_item i ON i.id=m.stock_item_id
JOIN document_line d ON d.id=m.line_id
WHERE (i.owner_id,i.consignment_id) IS DISTINCT FROM (d.owner_id,d.consignment_id);

SELECT r.id FROM reservation r JOIN stock_item i ON i.id=r.stock_item_id
JOIN document_line d ON d.id=r.line_id
WHERE (i.owner_id,i.consignment_id) IS DISTINCT FROM (d.owner_id,d.consignment_id);

SELECT i.id FROM stock_item i JOIN stock_owner o ON o.id=i.owner_id
LEFT JOIN consignment_agreement a ON a.id=i.consignment_id
WHERE (o.kind='CONSIGNOR')<>(i.consignment_id IS NOT NULL)
   OR (i.consignment_id IS NOT NULL AND a.owner_id<>i.owner_id);

-- Legacy unresolved stock is surfaced for review, never counted as COMPANY.
SELECT i.id,b.location_id,b.on_hand FROM stock_item i JOIN stock_owner o ON o.id=i.owner_id
JOIN stock_balance b ON b.stock_item_id=i.id WHERE o.kind='UNCLASSIFIED' AND b.on_hand<>0;
