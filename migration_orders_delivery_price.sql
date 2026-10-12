-- ============================================================
-- ORDERS — Add delivery_price column (shop checkout flow)
-- Mirrors custom_orders.delivery_price (migration_v2.sql)
-- ============================================================
ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_price DECIMAL(10,2) DEFAULT 0;
