CREATE TABLE IF NOT EXISTS station_batches (
    batch_id TEXT PRIMARY KEY,
    day_key TEXT NOT NULL,
    observations TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS frozen_revisions (
    revision INTEGER PRIMARY KEY,
    day_key TEXT NOT NULL,
    edition INTEGER NOT NULL,
    UNIQUE (day_key, edition)
);

CREATE TABLE IF NOT EXISTS frozen_groups (
    revision INTEGER NOT NULL REFERENCES frozen_revisions(revision),
    ordinal INTEGER NOT NULL,
    group_id INTEGER NOT NULL,
    body TEXT NOT NULL,
    PRIMARY KEY (revision, group_id),
    UNIQUE (revision, ordinal)
);

CREATE TABLE IF NOT EXISTS delivery_waves (
    revision INTEGER NOT NULL REFERENCES frozen_revisions(revision),
    wave TEXT NOT NULL,
    group_ids TEXT NOT NULL,
    PRIMARY KEY (revision, wave)
);

CREATE TABLE IF NOT EXISTS issued_parcels (
    parcel_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL REFERENCES frozen_revisions(revision),
    body TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS confirmed_groups (
    revision INTEGER NOT NULL,
    group_id INTEGER NOT NULL,
    PRIMARY KEY (revision, group_id),
    FOREIGN KEY (revision, group_id) REFERENCES frozen_groups(revision, group_id)
);
