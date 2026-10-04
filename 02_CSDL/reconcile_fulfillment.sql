-- Read-only B10 diagnostics. Run after 017; each result set should be empty.
-- Legacy NULL provenance is deliberately excluded, never silently classified.
SELECT t.id AS pick_task_id, t.consumed_quantity, coalesce(sum(fc.quantity),0) AS traced_quantity
FROM wms.pick_task t LEFT JOIN wms.package_line l ON l.pick_task_id=t.id
LEFT JOIN wms.fulfillment_consumption fc ON fc.package_line_id=l.id
WHERE t.target_quantity IS NOT NULL GROUP BY t.id
HAVING t.consumed_quantity <> coalesce(sum(fc.quantity),0);

SELECT l.id AS package_line_id,l.consumed_quantity,coalesce(sum(fc.quantity),0) AS traced_quantity
FROM wms.package_line l LEFT JOIN wms.fulfillment_consumption fc ON fc.package_line_id=l.id
WHERE l.pick_task_id IS NOT NULL GROUP BY l.id
HAVING l.consumed_quantity <> coalesce(sum(fc.quantity),0);

SELECT fc.id AS consumption_id FROM wms.fulfillment_consumption fc
JOIN wms.package_line l ON l.id=fc.package_line_id JOIN wms.package p ON p.id=l.package_id
JOIN wms.pick_task t ON t.id=l.pick_task_id JOIN wms.reservation r ON r.id=t.reservation_id
JOIN wms.reservation_consumption rc ON rc.id=fc.reservation_consumption_id
JOIN wms.stock_move m ON m.id=rc.move_id JOIN wms.inventory_transaction tx ON tx.id=m.transaction_id
WHERE rc.reservation_id<>r.id OR l.stock_item_id<>r.stock_item_id OR l.document_line_id<>r.line_id
  OR m.line_id<>l.document_line_id OR m.stock_item_id<>l.stock_item_id OR tx.document_id<>p.document_id
  OR m.source_location_id<>r.location_id OR tx.operation<>'ISSUE';

SELECT rc.id AS reservation_consumption_id,rc.quantity,sum(fc.quantity) AS packed_quantity
FROM wms.reservation_consumption rc JOIN wms.fulfillment_consumption fc ON fc.reservation_consumption_id=rc.id
GROUP BY rc.id HAVING sum(fc.quantity)<>rc.quantity;

SELECT r.id AS reservation_id,r.quantity-r.consumed-r.released AS remaining,
  sum(CASE WHEN t.status='DONE' THEN t.picked_quantity ELSE t.target_quantity END-t.consumed_quantity) AS assigned
FROM wms.reservation r JOIN wms.pick_task t ON t.reservation_id=r.id
WHERE t.target_quantity IS NOT NULL AND t.status<>'CANCELLED' GROUP BY r.id
HAVING sum(CASE WHEN t.status='DONE' THEN t.picked_quantity ELSE t.target_quantity END-t.consumed_quantity)
  > r.quantity-r.consumed-r.released;

SELECT t.id AS pick_task_id FROM wms.pick_task t JOIN wms.package_line l ON l.pick_task_id=t.id
JOIN wms.package p ON p.id=l.package_id WHERE t.target_quantity IS NOT NULL AND p.status<>'CANCELLED'
GROUP BY t.id HAVING sum(l.quantity-l.consumed_quantity)>t.picked_quantity-t.consumed_quantity
  OR (sum(l.quantity-l.consumed_quantity)>0 AND t.status<>'DONE');

SELECT l.id AS package_line_id FROM wms.package_line l JOIN wms.package p ON p.id=l.package_id
LEFT JOIN wms.pick_task t ON t.id=l.pick_task_id LEFT JOIN wms.reservation r ON r.id=t.reservation_id
LEFT JOIN wms.document_line dl ON dl.id=r.line_id
WHERE p.status IS NOT NULL AND (t.id IS NULL OR l.stock_item_id<>r.stock_item_id
  OR l.document_line_id<>r.line_id OR p.document_id<>dl.document_id);
