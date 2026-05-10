-- ============================================================
-- NOYS 3D PRINTS — PRODUCT MEDIA (gallery + turntable video)
-- Run this in Supabase SQL Editor
-- ============================================================
-- Adds support for multiple photos and an optional video per
-- shop product. The existing products.image_url stays as the
-- thumbnail / cart image so existing data keeps working.
-- ============================================================

CREATE TABLE IF NOT EXISTS product_media (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id  UUID        NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    url         TEXT        NOT NULL,
    media_type  TEXT        NOT NULL CHECK (media_type IN ('image', 'video')),
    sort_order  INTEGER     NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_product_media_product_id
    ON product_media(product_id);

CREATE INDEX IF NOT EXISTS idx_product_media_sort
    ON product_media(product_id, sort_order);

-- Backfill: turn each existing product's single image_url into a
-- product_media row so every existing product has a gallery entry.
INSERT INTO product_media (product_id, url, media_type, sort_order)
SELECT id, image_url, 'image', 0
FROM products
WHERE image_url IS NOT NULL
  AND image_url <> ''
  AND NOT EXISTS (
      SELECT 1 FROM product_media pm WHERE pm.product_id = products.id
  );
