-- User drawings on the chart, per symbol. Prices are in the series' own units
-- (Yahoo: split-adjusted), times are ISO session dates.
CREATE TABLE drawings (
    id         INTEGER PRIMARY KEY,
    symbol     TEXT NOT NULL,
    kind       TEXT NOT NULL,
    data       TEXT NOT NULL,   -- JSON: {"points": [{"time": ..., "price": ...}], "text": ...}
    created_at TEXT NOT NULL
);
CREATE INDEX drawings_symbol ON drawings (symbol, id);
