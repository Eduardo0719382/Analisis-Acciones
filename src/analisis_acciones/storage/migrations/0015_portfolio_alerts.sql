-- Paper portfolio alerts (0 = off) and the conditions already announced (re-armed when
-- they stop being true).
ALTER TABLE paper_portfolios ADD COLUMN alert_loss_pct REAL NOT NULL DEFAULT 0;
ALTER TABLE paper_portfolios ADD COLUMN alert_drift_pts REAL NOT NULL DEFAULT 0;
ALTER TABLE paper_portfolios ADD COLUMN alert_drawdown_pct REAL NOT NULL DEFAULT 0;
CREATE TABLE paper_alert_state (
    portfolio_id INTEGER NOT NULL REFERENCES paper_portfolios(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    PRIMARY KEY (portfolio_id, key)
);
