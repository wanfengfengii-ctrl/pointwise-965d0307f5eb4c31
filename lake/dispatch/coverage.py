def record_coverage(db, revision, group_ids):
    db.executemany(
        'INSERT INTO confirmed_groups (revision, group_id) VALUES (?, ?) '
        'ON CONFLICT (revision, group_id) DO NOTHING',
        ((revision, group_id) for group_id in group_ids),
    )


def confirmed_groups(db, revision):
    rows = db.execute('SELECT group_id FROM confirmed_groups WHERE revision = ?', (revision,))
    return frozenset(group_id for group_id, in rows)
