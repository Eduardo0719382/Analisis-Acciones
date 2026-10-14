-- Optional note shown with an alert (e.g. which Elliott count or chart pattern
-- level it watches). Plain text written by the application.
ALTER TABLE alerts ADD COLUMN note TEXT NOT NULL DEFAULT '';
