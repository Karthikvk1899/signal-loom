import os
from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

pool = ConnectionPool(os.environ.get("DATABASE_URL", "postgresql://loom:loom@localhost/loom"),
                      open=False, min_size=1, max_size=10, timeout=5,
                      kwargs={"row_factory": dict_row, "options": "-c statement_timeout=5000 -c lock_timeout=3000"})


@contextmanager
def connection():
    with pool.connection() as conn, conn.transaction():
        yield conn
