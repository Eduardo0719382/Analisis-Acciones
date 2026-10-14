-- Commission schedule per paper portfolio (applied to new trades): fixed amount per
-- trade plus a percentage of the traded value, with a minimum. Dividends credited
-- automatically unless switched off. Trade reviews for the trading journal.
ALTER TABLE paper_portfolios ADD COLUMN commission_fixed REAL NOT NULL DEFAULT 0;
ALTER TABLE paper_portfolios ADD COLUMN commission_pct REAL NOT NULL DEFAULT 0;
ALTER TABLE paper_portfolios ADD COLUMN commission_min REAL NOT NULL DEFAULT 0;
ALTER TABLE paper_portfolios ADD COLUMN apply_dividends INTEGER NOT NULL DEFAULT 1;
ALTER TABLE paper_trades ADD COLUMN review TEXT NOT NULL DEFAULT '';
