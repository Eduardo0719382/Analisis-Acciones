-- Paper portfolio taxes: withholding on dividends (deducted when credited) and an
-- estimated tax rate on realised gains (shown, not deducted).
ALTER TABLE paper_portfolios ADD COLUMN dividend_withholding_pct REAL NOT NULL DEFAULT 0;
ALTER TABLE paper_portfolios ADD COLUMN capital_gains_tax_pct REAL NOT NULL DEFAULT 0;
