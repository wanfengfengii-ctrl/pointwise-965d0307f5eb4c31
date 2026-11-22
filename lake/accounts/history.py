from lake.accounts.snapshots import load_snapshot


def read(db, account_id):
    """Retrieve the immutable account issued under this number, or None."""
    return load_snapshot(db, account_id)
