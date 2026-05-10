-- ============================================================
-- NOYS 3D PRINTS — Fix old generations where a .glb URL ended up
-- in image_url because of a parsing bug in the background poll.
-- Run this once in Supabase SQL Editor.
-- ============================================================
-- Symptom: preview page shows a static image only (no rotation)
-- because stl_url is NULL but image_url contains the GLB URL.
-- Fix: move the GLB URL to stl_url, blank image_url so the
-- frontend's "image only" branch isn't triggered.
-- ============================================================

UPDATE generations
SET
    stl_url   = image_url,
    image_url = NULL
WHERE
    stl_url IS NULL
    AND image_url IS NOT NULL
    AND (
        image_url ILIKE '%.glb%'
        OR image_url ILIKE '%.gltf%'
        OR image_url ILIKE '%/model_%.glb%'
        OR image_url ILIKE '%/base_model%'
    );
