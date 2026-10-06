-- B24 independent read-only diagnostics; every result set must be empty.
-- Run all reconcile_*.sql within one REPEATABLE READ / READ ONLY transaction.
SELECT b.stock_item_id,b.location_id FROM wms.stock_balance b
WHERE b.on_hand<0 OR b.reserved<0 OR b.reserved>b.on_hand;

-- serial_position must match the sole physical positive balance, including owner.
SELECT coalesce(p.serial_id,i.serial_id) AS serial_id
FROM wms.serial_position p FULL JOIN (
 SELECT si.serial_id,b.location_id,si.id AS stock_item_id FROM wms.stock_balance b
 JOIN wms.stock_item si ON si.id=b.stock_item_id WHERE si.serial_id IS NOT NULL AND b.on_hand>0
) i ON i.serial_id=p.serial_id
LEFT JOIN wms.stock_move last_move ON last_move.id=p.last_move_id
WHERE p.serial_id IS NULL OR i.serial_id IS NULL OR p.location_id<>i.location_id
 OR last_move.stock_item_id<>i.stock_item_id OR last_move.destination_location_id<>p.location_id;

-- Consumption tracing must agree with the reservation aggregate.
SELECT r.id FROM wms.reservation r LEFT JOIN wms.reservation_consumption c ON c.reservation_id=r.id
GROUP BY r.id HAVING r.consumed<>coalesce(sum(c.quantity),0);

-- Each reversal preserves identity/quantity and exactly swaps both legs.
SELECT r.id FROM wms.stock_move r JOIN wms.stock_move s ON s.id=r.reverses_move_id
JOIN wms.inventory_transaction rt ON rt.id=r.transaction_id
WHERE r.stock_item_id<>s.stock_item_id OR r.quantity_base<>s.quantity_base
 OR r.source_location_id<>s.destination_location_id OR r.destination_location_id<>s.source_location_id
 OR rt.reverses_transaction_id<>s.transaction_id;

SELECT t.id FROM wms.inventory_transaction t WHERE t.reverses_transaction_id IS NOT NULL
 AND (SELECT count(*) FROM wms.stock_move m WHERE m.transaction_id=t.id)
  <> (SELECT count(*) FROM wms.stock_move m WHERE m.transaction_id=t.reverses_transaction_id);

-- Posting must leave both an audit record and a versioned outbox event in the same transaction.
SELECT t.id FROM wms.inventory_transaction t
WHERE NOT EXISTS (SELECT 1 FROM wms.audit_event a WHERE a.after_data->>'transaction_id'=t.id::text)
   OR NOT EXISTS (SELECT 1 FROM wms.outbox_event e WHERE e.payload->>'transaction_id'=t.id::text);
