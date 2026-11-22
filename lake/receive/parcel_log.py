from lake.db import key
from lake.dispatch.parcels import DeliveryParcel


def load_accepted_parcel(db, parcel_id):
    key(parcel_id, 'parcel id', 'BAD_PARCEL')
    row = db.execute('SELECT body FROM accepted_parcels WHERE parcel_id = ?', (parcel_id,)).fetchone()
    return None if row is None else DeliveryParcel.from_json(row[0])


def record_accepted_parcel(db, parcel):
    db.execute(
        'INSERT INTO accepted_parcels (parcel_id, revision, body) VALUES (?, ?, ?)',
        (parcel.parcel_id, parcel.manifest.revision, parcel.to_json()),
    )
