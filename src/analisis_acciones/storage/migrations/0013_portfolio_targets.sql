-- Target weights per paper portfolio for rebalancing (percent of the total value).
CREATE TABLE paper_targets (
    portfolio_id INTEGER NOT NULL REFERENCES paper_portfolios(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    weight_pct REAL NOT NULL CHECK (weight_pct > 0 AND weight_pct <= 100),
    PRIMARY KEY (portfolio_id, symbol)
);
