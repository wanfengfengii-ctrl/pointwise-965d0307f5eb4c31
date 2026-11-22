CREATE TABLE IF NOT EXISTS received_catalogs (
    revision INTEGER PRIMARY KEY,
    day_key TEXT NOT NULL,
    edition INTEGER NOT NULL,
    group_ids TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accepted_parcels (
    parcel_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL REFERENCES received_catalogs(revision),
    body TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS received_groups (
    revision INTEGER NOT NULL REFERENCES received_catalogs(revision),
    group_id INTEGER NOT NULL,
    body TEXT NOT NULL,
    first_parcel_id TEXT NOT NULL REFERENCES accepted_parcels(parcel_id),
    PRIMARY KEY (revision, group_id)
);

CREATE TABLE IF NOT EXISTS daily_accounts (
    account_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL UNIQUE REFERENCES received_catalogs(revision),
    day_key TEXT NOT NULL,
    edition INTEGER NOT NULL,
    totals TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS account_groups (
    account_id TEXT NOT NULL REFERENCES daily_accounts(account_id),
    ordinal INTEGER NOT NULL,
    group_id INTEGER NOT NULL,
    body TEXT NOT NULL,
    first_parcel_id TEXT NOT NULL,
    PRIMARY KEY (account_id, ordinal),
    UNIQUE (account_id, group_id)
);

CREATE TABLE IF NOT EXISTS catalog_anchors (
    revision INTEGER PRIMARY KEY REFERENCES received_catalogs(revision),
    anchor TEXT NOT NULL,
    mode TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS received_evidence (
    revision INTEGER NOT NULL,
    group_id INTEGER NOT NULL,
    body TEXT NOT NULL,
    PRIMARY KEY (revision, group_id),
    FOREIGN KEY (revision, group_id) REFERENCES received_groups(revision, group_id)
);
