-- ============================================================
-- APP SETTINGS — Single-row config table for site-wide settings
-- (modeled on the existing delivery_settings table)
-- ============================================================
CREATE TABLE IF NOT EXISTS app_settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    default_free_credits INTEGER DEFAULT 15,
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Insert single settings row, seeded with the existing behavior (15)
INSERT INTO app_settings (default_free_credits)
SELECT 15
WHERE NOT EXISTS (SELECT 1 FROM app_settings);
