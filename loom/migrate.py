"""Explicit schema initialization. Run once before API replicas start."""

import os
from pathlib import Path

import psycopg


def main():
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(821475)")
        conn.execute(Path(__file__).with_name("schema.sql").read_text())


if __name__ == "__main__":
    main()
