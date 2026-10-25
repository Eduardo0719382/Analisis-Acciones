-- Cash movements of a paper portfolio that are not trades: deposits, withdrawals and, as
-- reported by a broker, cash dividends, interest and fees. Amount is positive, in currency.
CREATE TABLE paper_cash (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id INTEGER NOT NULL REFERENCES paper_portfolios(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('deposit', 'withdrawal', 'cash_dividend', 'interest', 'fee')),
    amount REAL NOT NULL CHECK (amount > 0),
    currency TEXT NOT NULL DEFAULT 'USD',
    fx_rate REAL NOT NULL DEFAULT 1,
    symbol TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX paper_cash_portfolio ON paper_cash (portfolio_id, day);
