-- Trading currency of each symbol as reported by the data source (cached).
CREATE TABLE symbol_currency (
    symbol     TEXT PRIMARY KEY NOT NULL,
    currency   TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
-- Paper trades keep the price in the asset's currency and the exchange rate to dollars
-- of the trade date, so the recorded history does not change later.
ALTER TABLE paper_trades ADD COLUMN currency TEXT NOT NULL DEFAULT 'USD';
ALTER TABLE paper_trades ADD COLUMN fx_rate REAL NOT NULL DEFAULT 1;
