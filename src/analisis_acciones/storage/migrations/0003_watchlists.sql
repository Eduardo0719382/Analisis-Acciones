CREATE TABLE watchlists (
    id       INTEGER PRIMARY KEY,
    name     TEXT NOT NULL UNIQUE COLLATE NOCASE,
    position INTEGER NOT NULL
);

CREATE TABLE watchlist_items (
    watchlist_id INTEGER NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
    symbol       TEXT NOT NULL,
    position     INTEGER NOT NULL,
    added_at     TEXT NOT NULL,
    PRIMARY KEY (watchlist_id, symbol)
);
