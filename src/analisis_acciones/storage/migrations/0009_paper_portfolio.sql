-- Paper (simulated) portfolios: no real money or broker involved.
CREATE TABLE paper_portfolios (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    initial_cash  REAL NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE paper_trades (
    id            INTEGER PRIMARY KEY,
    portfolio_id  INTEGER NOT NULL REFERENCES paper_portfolios(id) ON DELETE CASCADE,
    symbol        TEXT NOT NULL,
    side          TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    quantity      REAL NOT NULL CHECK (quantity > 0),
    price         REAL NOT NULL CHECK (price > 0),
    commission    REAL NOT NULL DEFAULT 0 CHECK (commission >= 0),
    trade_date    TEXT NOT NULL,          -- ISO session date
    note          TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL
);
CREATE INDEX paper_trades_portfolio ON paper_trades (portfolio_id, trade_date, id);
