-- NeoMoPyeonHaeng 행사 상품 Supabase 백업 스키마
-- Supabase SQL Editor에서 실행하세요.

CREATE TABLE IF NOT EXISTS event_snapshots (
    store TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    product_count INTEGER NOT NULL DEFAULT 0,
    products JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS events_meta (
    id TEXT PRIMARY KEY DEFAULT 'current',
    version TEXT,
    brands JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_event_snapshots_updated_at
    ON event_snapshots (updated_at DESC);

-- 앱(anon key)용 읽기 정책 예시 — service role 크롤러는 RLS를 우회합니다.
ALTER TABLE event_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE events_meta ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow public read event_snapshots"
    ON event_snapshots FOR SELECT
    USING (true);

CREATE POLICY "Allow public read events_meta"
    ON events_meta FOR SELECT
    USING (true);

-- 매장 위치 (브랜드별 shop_code 기준 upsert)
CREATE TABLE IF NOT EXISTS store_locations (
    store TEXT NOT NULL,
    shop_code TEXT NOT NULL,
    name TEXT NOT NULL,
    address TEXT NOT NULL,
    phone TEXT NOT NULL DEFAULT '',
    lat DOUBLE PRECISION NOT NULL,
    lng DOUBLE PRECISION NOT NULL,
    geohash TEXT NOT NULL,
    services JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (store, shop_code)
);

CREATE INDEX IF NOT EXISTS idx_store_locations_store_geohash
    ON store_locations (store, geohash);

CREATE INDEX IF NOT EXISTS idx_store_locations_lat_lng
    ON store_locations (lat, lng);

CREATE TABLE IF NOT EXISTS locations_meta (
    id TEXT PRIMARY KEY DEFAULT 'current',
    version TEXT,
    brands JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE store_locations ENABLE ROW LEVEL SECURITY;
ALTER TABLE locations_meta ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow public read store_locations"
    ON store_locations FOR SELECT
    USING (true);

CREATE POLICY "Allow public read locations_meta"
    ON locations_meta FOR SELECT
    USING (true);
