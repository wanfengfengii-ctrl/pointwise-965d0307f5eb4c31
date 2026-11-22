import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class LakeError(ValueError):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(f'{code}: {detail}')


def key(value, field, code):
    if type(value) is not str or not value or value.strip() != value or '\x00' in value:
        raise LakeError(code, f'invalid {field}')
    try:
        value.encode('utf-8')
    except UnicodeError as exc:
        raise LakeError(code, f'invalid UTF-8 in {field}') from exc
    return value


def positive_id(value, field, code):
    if type(value) is not int or not 0 < value < 2**63:
        raise LakeError(code, f'invalid {field}')
    return value


def sequence(value, field, code):
    if type(value) not in (tuple, list):
        raise LakeError(code, f'{field} requires a list or tuple')
    return tuple(value)


def require_fields(value, fields, code):
    if type(value) is not dict or value.keys() != set(fields):
        raise LakeError(code, 'unexpected material fields')


def encode_liters(value):
    return None if value is None else format(value, 'x')


def decode_liters(value, code):
    if value is None:
        return None
    if type(value) is not str:
        raise LakeError(code, 'liters require hexadecimal text or null')
    try:
        liters = int(value, 16)
    except ValueError as exc:
        raise LakeError(code, 'invalid liters') from exc
    if encode_liters(liters) != value:
        raise LakeError(code, 'noncanonical liters')
    return liters


def pack(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


@contextmanager
def atomic(db):
    if db.in_transaction:
        raise LakeError('ACTIVE_TRANSACTION', 'operation requires an idle connection')
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise


def _initialize(db, filename):
    if db.in_transaction:
        raise LakeError('ACTIVE_TRANSACTION', 'initialization requires an idle connection')
    script = Path(__file__).with_name(filename).read_text(encoding='utf-8')
    db.execute('PRAGMA foreign_keys = ON')
    try:
        db.executescript(f'BEGIN IMMEDIATE;\n{script}\nCOMMIT;')
    except BaseException:
        db.rollback()
        raise


def initialize_source(db):
    _initialize(db, 'source.sql')


def initialize_warehouse(db):
    _initialize(db, 'warehouse.sql')


def _connect(path, initialize):
    db = sqlite3.connect(path, isolation_level=None)
    try:
        initialize(db)
    except BaseException:
        db.close()
        raise
    return db


def connect_source(path):
    return _connect(path, initialize_source)


def connect_warehouse(path):
    return _connect(path, initialize_warehouse)
