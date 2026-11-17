import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "boothops.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # lets us access columns by name
    conn.execute("PRAGMA journal_mode=WAL")  # safer for concurrent writes
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS booths (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            location    TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS bookings (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            booth_id        INTEGER NOT NULL,
            candidate_name  TEXT NOT NULL,
            candidate_email TEXT NOT NULL,
            interviewer_name TEXT NOT NULL,
            start_time      TEXT NOT NULL,
            end_time        TEXT NOT NULL,
            checkin_code    TEXT NOT NULL UNIQUE,
            status          TEXT NOT NULL DEFAULT 'scheduled',
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (booth_id) REFERENCES booths(id),
            CHECK (status IN ('scheduled','checked_in','in_progress','completed','interrupted','cancelled'))
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id      INTEGER NOT NULL UNIQUE,
            checked_in_at   TEXT,
            completed_at    TEXT,
            notes           TEXT,
            FOREIGN KEY (booking_id) REFERENCES bookings(id)
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type  TEXT NOT NULL,
            booking_id  INTEGER,
            booth_id    INTEGER,
            actor       TEXT,
            detail      TEXT,
            occurred_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_bookings_booth_time
            ON bookings(booth_id, start_time, end_time);

        CREATE INDEX IF NOT EXISTS idx_audit_log_booking
            ON audit_log(booking_id);

        CREATE INDEX IF NOT EXISTS idx_audit_log_occurred
            ON audit_log(occurred_at);
    """)

    conn.commit()
    conn.close()
    print("Database initialized.")


def audit_event(conn, event_type, booking_id=None, booth_id=None, actor=None, detail=None):
    """
    Write an immutable audit log entry using an existing connection.
    Called inside the same transaction as the action it describes,
    so the log entry and the state change are atomic.
    """
    conn.execute("""
        INSERT INTO audit_log (event_type, booking_id, booth_id, actor, detail, occurred_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
    """, (event_type, booking_id, booth_id, actor, detail))


if __name__ == "__main__":
    init_db()
