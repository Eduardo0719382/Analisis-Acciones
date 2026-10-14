-- Cached intraday bars (1h, 15m). Times are New York exchange wall-clock times
-- (naive ISO "YYYY-MM-DDTHH:MM:SS"), the start of each bar. Kept beyond the
-- provider's window (Yahoo serves 60 days of 15m bars) so history accumulates.
CREATE TABLE intraday_bars (
    symbol    TEXT NOT NULL,
    interval  TEXT NOT NULL,
    ts        TEXT NOT NULL,
    open      REAL NOT NULL,
    high      REAL NOT NULL,
    low       REAL NOT NULL,
    close     REAL NOT NULL,
    adj_close REAL,
    volume    REAL,
    dividends REAL NOT NULL DEFAULT 0,
    splits    REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, interval, ts)
) WITHOUT ROWID;

CREATE TABLE intraday_meta (
    symbol     TEXT NOT NULL,
    interval   TEXT NOT NULL,
    source     TEXT NOT NULL,
    fetched_at TEXT NOT NULL,         -- ISO UTC timestamp of the last successful fetch
    PRIMARY KEY (symbol, interval)
);
