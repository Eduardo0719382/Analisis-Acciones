-- Cached daily bars. Weekly/monthly bars are derived on load.
-- Symbols imported from CSV are stored with a "CSV:" prefix.
CREATE TABLE daily_bars (
    symbol    TEXT NOT NULL,
    date      TEXT NOT NULL,          -- ISO session date, YYYY-MM-DD
    open      REAL NOT NULL,
    high      REAL NOT NULL,
    low       REAL NOT NULL,
    close     REAL NOT NULL,
    adj_close REAL,
    volume    REAL,                   -- NULL when the source has no volume
    dividends REAL NOT NULL DEFAULT 0,
    splits    REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, date)
) WITHOUT ROWID;

CREATE TABLE series_meta (
    symbol     TEXT PRIMARY KEY NOT NULL,
    source     TEXT NOT NULL,
    fetched_at TEXT NOT NULL,         -- ISO UTC timestamp of the last successful fetch
    first_date TEXT,
    last_date  TEXT
);

CREATE TABLE recent_symbols (
    symbol    TEXT PRIMARY KEY NOT NULL,
    name      TEXT,
    opened_at TEXT NOT NULL
);
