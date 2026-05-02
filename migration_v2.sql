-- ============================================================
-- NOYS 3D PRINTS — DATABASE MIGRATION V2
-- Run this in Supabase SQL Editor
-- ============================================================

-- ============================================================
-- 1. MODEL SIZES — 12 sizes with individually editable prices
-- ============================================================
CREATE TABLE IF NOT EXISTS model_sizes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    size_mm INTEGER NOT NULL UNIQUE,
    price DECIMAL(10,2) NOT NULL,
    is_on_sale BOOLEAN DEFAULT false,
    sale_price DECIMAL(10,2) DEFAULT NULL,
    is_active BOOLEAN DEFAULT true,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Seed the 12 required sizes with placeholder prices (edit in admin)
INSERT INTO model_sizes (size_mm, price, sort_order) VALUES
    (80,  15.00, 1),
    (100, 18.00, 2),
    (120, 22.00, 3),
    (140, 26.00, 4),
    (160, 32.00, 5),
    (180, 38.00, 6),
    (200, 45.00, 7),
    (220, 52.00, 8),
    (240, 60.00, 9),
    (260, 70.00, 10),
    (280, 80.00, 11),
    (300, 90.00, 12)
ON CONFLICT (size_mm) DO NOTHING;


-- ============================================================
-- 2. FINISH OPTIONS — Unpainted, DIY Paint Kit, Professionally Painted
-- ============================================================
CREATE TABLE IF NOT EXISTS finish_options (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    base_price DECIMAL(10,2) DEFAULT 0,
    is_on_sale BOOLEAN DEFAULT false,
    sale_price DECIMAL(10,2) DEFAULT NULL,
    is_active BOOLEAN DEFAULT true,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

INSERT INTO finish_options (name, slug, description, base_price, sort_order) VALUES
    ('Unpainted Model', 'unpainted', 'Receive the raw 3D printed model only.', 0.00, 1),
    ('Model + DIY Paint Kit', 'diy_kit', 'Receive the model plus a paint kit with brushes. Kit contents may vary.', 12.99, 2),
    ('Professionally Painted Model', 'painted', 'Receive a fully painted finished model by our artists. Premium painting service.', 0.00, 3)
ON CONFLICT (slug) DO NOTHING;


-- ============================================================
-- 3. PAINTING TIERS — Small, Medium, Large with editable prices
-- ============================================================
CREATE TABLE IF NOT EXISTS painting_tiers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL,
    price DECIMAL(10,2) NOT NULL,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

INSERT INTO painting_tiers (name, price, sort_order) VALUES
    ('Small', 15.00, 1),
    ('Medium', 25.00, 2),
    ('Large', 40.00, 3)
ON CONFLICT DO NOTHING;


-- ============================================================
-- 4. PAINTING TIER MAPPINGS — Which sizes belong to which tier
-- ============================================================
CREATE TABLE IF NOT EXISTS painting_tier_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    painting_tier_id UUID NOT NULL REFERENCES painting_tiers(id) ON DELETE CASCADE,
    model_size_id UUID NOT NULL REFERENCES model_sizes(id) ON DELETE CASCADE,
    price_override DECIMAL(10,2) DEFAULT NULL,
    UNIQUE(model_size_id)
);

-- Map sizes to tiers (Small: 80-140mm, Medium: 160-220mm, Large: 240-300mm)
-- This uses a DO block to look up IDs dynamically
DO $$
DECLARE
    tier_small UUID;
    tier_medium UUID;
    tier_large UUID;
BEGIN
    SELECT id INTO tier_small FROM painting_tiers WHERE name = 'Small';
    SELECT id INTO tier_medium FROM painting_tiers WHERE name = 'Medium';
    SELECT id INTO tier_large FROM painting_tiers WHERE name = 'Large';

    -- Small tier: 80, 100, 120, 140
    INSERT INTO painting_tier_mappings (painting_tier_id, model_size_id)
    SELECT tier_small, id FROM model_sizes WHERE size_mm IN (80, 100, 120, 140)
    ON CONFLICT (model_size_id) DO NOTHING;

    -- Medium tier: 160, 180, 200, 220
    INSERT INTO painting_tier_mappings (painting_tier_id, model_size_id)
    SELECT tier_medium, id FROM model_sizes WHERE size_mm IN (160, 180, 200, 220)
    ON CONFLICT (model_size_id) DO NOTHING;

    -- Large tier: 240, 260, 280, 300
    INSERT INTO painting_tier_mappings (painting_tier_id, model_size_id)
    SELECT tier_large, id FROM model_sizes WHERE size_mm IN (240, 260, 280, 300)
    ON CONFLICT (model_size_id) DO NOTHING;
END $$;


-- ============================================================
-- 5. PAINT COLORS — Available extra paint pot colors
-- ============================================================
CREATE TABLE IF NOT EXISTS paint_colors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL,
    hex_code VARCHAR(7) DEFAULT '#000000',
    price DECIMAL(10,2) NOT NULL DEFAULT 2.99,
    is_on_sale BOOLEAN DEFAULT false,
    sale_price DECIMAL(10,2) DEFAULT NULL,
    is_active BOOLEAN DEFAULT true,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Seed some default paint colors
INSERT INTO paint_colors (name, hex_code, price, sort_order) VALUES
    ('Pure White',      '#FFFFFF', 2.99, 1),
    ('Jet Black',       '#1A1A1A', 2.99, 2),
    ('Crimson Red',     '#DC143C', 2.99, 3),
    ('Royal Blue',      '#4169E1', 2.99, 4),
    ('Forest Green',    '#228B22', 2.99, 5),
    ('Golden Yellow',   '#FFD700', 2.99, 6),
    ('Silver Metallic', '#C0C0C0', 3.49, 7),
    ('Bronze Metallic', '#CD7F32', 3.49, 8),
    ('Flesh Tone',      '#FFCBA4', 2.99, 9),
    ('Dark Brown',      '#654321', 2.99, 10),
    ('Purple Royal',    '#6A0DAD', 2.99, 11),
    ('Orange Flame',    '#FF6600', 2.99, 12)
ON CONFLICT DO NOTHING;


-- ============================================================
-- 6. DELIVERY SETTINGS — Free delivery threshold + standard price
-- ============================================================
CREATE TABLE IF NOT EXISTS delivery_settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    free_delivery_threshold DECIMAL(10,2) DEFAULT 50.00,
    standard_delivery_price DECIMAL(10,2) DEFAULT 4.99,
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Insert single settings row
INSERT INTO delivery_settings (free_delivery_threshold, standard_delivery_price)
SELECT 50.00, 4.99
WHERE NOT EXISTS (SELECT 1 FROM delivery_settings);


-- ============================================================
-- 7. MODIFY PLANS TABLE — Add discount percentage for memberships
-- ============================================================
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'plans' AND column_name = 'discount_percentage'
    ) THEN
        ALTER TABLE plans ADD COLUMN discount_percentage DECIMAL(5,2) DEFAULT 0;
    END IF;
END $$;

-- Update existing plans with discount percentages
UPDATE plans SET discount_percentage = 0   WHERE LOWER(name) = 'starter';
UPDATE plans SET discount_percentage = 10  WHERE LOWER(name) = 'bronze';
UPDATE plans SET discount_percentage = 15  WHERE LOWER(name) = 'silver';
UPDATE plans SET discount_percentage = 25  WHERE LOWER(name) = 'gold';


-- ============================================================
-- 8. ENSURE shipping_address COLUMN ON USERS
-- ============================================================
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'shipping_address'
    ) THEN
        ALTER TABLE users ADD COLUMN shipping_address JSONB DEFAULT NULL;
    END IF;
END $$;


-- ============================================================
-- 9. CUSTOM ORDERS — The main new order table for custom models
-- ============================================================
CREATE TABLE IF NOT EXISTS custom_orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_number SERIAL,
    user_id UUID NOT NULL REFERENCES users(id),

    -- Reference image
    reference_image_url TEXT,
    generation_id UUID REFERENCES generations(id),
    image_source VARCHAR(20) NOT NULL DEFAULT 'upload',

    -- Product configuration (denormalized for order history)
    model_size_id UUID REFERENCES model_sizes(id),
    size_mm INTEGER NOT NULL,
    size_price DECIMAL(10,2) NOT NULL,

    finish_option_id UUID REFERENCES finish_options(id),
    finish_name VARCHAR(255) NOT NULL,
    finish_price DECIMAL(10,2) NOT NULL DEFAULT 0,

    painting_tier_id UUID REFERENCES painting_tiers(id),
    painting_tier_name VARCHAR(100),
    painting_price DECIMAL(10,2) DEFAULT 0,

    -- Extras total (sum of order_paint_extras)
    extras_total DECIMAL(10,2) DEFAULT 0,

    -- Pricing breakdown
    subtotal_before_discount DECIMAL(10,2) NOT NULL,
    membership_tier VARCHAR(50) DEFAULT NULL,
    discount_percentage DECIMAL(5,2) DEFAULT 0,
    discount_amount DECIMAL(10,2) DEFAULT 0,
    delivery_price DECIMAL(10,2) DEFAULT 0,
    total DECIMAL(10,2) NOT NULL,

    -- Shipping
    shipping_address JSONB,

    -- Order status workflow
    status VARCHAR(50) DEFAULT 'new_order',
    review_status VARCHAR(50) DEFAULT 'pending',

    -- Agreement
    agreement_accepted BOOLEAN DEFAULT false,
    agreement_accepted_at TIMESTAMPTZ,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Index for fast lookups
CREATE INDEX IF NOT EXISTS idx_custom_orders_user_id ON custom_orders(user_id);
CREATE INDEX IF NOT EXISTS idx_custom_orders_status ON custom_orders(status);
CREATE INDEX IF NOT EXISTS idx_custom_orders_review ON custom_orders(review_status);


-- ============================================================
-- 10. ORDER PAINT EXTRAS — Extra paint pots per custom order
-- ============================================================
CREATE TABLE IF NOT EXISTS order_paint_extras (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID NOT NULL REFERENCES custom_orders(id) ON DELETE CASCADE,
    paint_color_id UUID REFERENCES paint_colors(id),
    color_name VARCHAR(100) NOT NULL,
    hex_code VARCHAR(7) DEFAULT '#000000',
    quantity INTEGER NOT NULL DEFAULT 1,
    unit_price DECIMAL(10,2) NOT NULL,
    is_on_sale BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_order_paint_extras_order ON order_paint_extras(order_id);


-- ============================================================
-- 11. ORDER NOTES — Admin notes on custom orders
-- ============================================================
CREATE TABLE IF NOT EXISTS order_notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID NOT NULL REFERENCES custom_orders(id) ON DELETE CASCADE,
    admin_id UUID REFERENCES users(id),
    admin_name VARCHAR(255),
    note TEXT NOT NULL,
    note_type VARCHAR(50) DEFAULT 'internal',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_order_notes_order ON order_notes(order_id);


-- ============================================================
-- 12. CONTACTS TABLE — Fix the missing contact form storage
-- ============================================================
CREATE TABLE IF NOT EXISTS contacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL,
    message TEXT NOT NULL,
    is_read BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now()
);


-- ============================================================
-- DONE! Verify tables were created
-- ============================================================
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;
