DROP TABLE IF EXISTS product_colours CASCADE;

CREATE TABLE product_colours (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id   UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  name         VARCHAR(100) NOT NULL,
  hex_code     VARCHAR(7)   NOT NULL,
  sort_order   INTEGER NOT NULL DEFAULT 0,
  created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_product_colours_product_id ON product_colours(product_id);
