-- Bar interval an alert is evaluated on ("1D", "1h", "15m"). last_bar then holds
-- the ISO date (daily) or ISO date-time (intraday) of the last evaluated bar.
ALTER TABLE alerts ADD COLUMN interval TEXT NOT NULL DEFAULT '1D';
