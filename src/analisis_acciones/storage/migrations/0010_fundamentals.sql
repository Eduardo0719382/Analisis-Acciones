-- Last fundamentals fetched per symbol (JSON of models.market.Fundamentals), so the
-- panel can show them offline, marked with their fetch time.
CREATE TABLE fundamentals_cache (
    symbol     TEXT PRIMARY KEY NOT NULL,
    fetched_at TEXT NOT NULL,
    payload    TEXT NOT NULL
);
