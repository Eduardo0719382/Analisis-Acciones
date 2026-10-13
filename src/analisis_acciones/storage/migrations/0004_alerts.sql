CREATE TABLE alerts (
    id                INTEGER PRIMARY KEY,
    symbol            TEXT NOT NULL,
    kind              TEXT NOT NULL,
    params            TEXT NOT NULL,      -- JSON object
    enabled           INTEGER NOT NULL DEFAULT 1,
    armed             INTEGER NOT NULL DEFAULT 1,
    last_bar          TEXT,               -- ISO date of the last evaluated bar
    last_triggered_at TEXT,
    created_at        TEXT NOT NULL
);

CREATE TABLE alert_events (
    id           INTEGER PRIMARY KEY,
    alert_id     INTEGER REFERENCES alerts(id) ON DELETE SET NULL,
    symbol       TEXT NOT NULL,
    description  TEXT NOT NULL,
    message      TEXT NOT NULL,
    bar_date     TEXT NOT NULL,
    triggered_at TEXT NOT NULL
);
CREATE INDEX alert_events_time ON alert_events (triggered_at DESC);
