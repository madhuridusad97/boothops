import csv
import io
from db import get_connection


def get_utilization_stats(date=None):
    """
    Returns utilization analytics for a given date (defaults to today).

    Metrics returned:
    - total_bookings: how many slots were booked
    - completed: interviews that finished successfully
    - no_shows: scheduled but never checked in (interrupted or still scheduled past end time)
    - cancelled: cancelled before check-in
    - avg_session_minutes: average duration of completed sessions
    - busiest_hour: the hour with most check-ins
    - utilization_by_booth: per-booth breakdown
    - utilization_rate: completed / total_bookings (excluding cancelled)
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()

        if not date:
            date = _today()

        # --- Overall counts ---
        cursor.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'completed'  THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status = 'cancelled'  THEN 1 ELSE 0 END) as cancelled,
                SUM(CASE WHEN status = 'interrupted' THEN 1 ELSE 0 END) as interrupted,
                SUM(CASE WHEN status = 'scheduled'  THEN 1 ELSE 0 END) as scheduled,
                SUM(CASE WHEN status = 'checked_in' THEN 1 ELSE 0 END) as checked_in
            FROM bookings
            WHERE DATE(start_time) = ?
        """, (date,))
        counts = dict(cursor.fetchone())

        # --- Average session duration (minutes) for completed sessions ---
        cursor.execute("""
            SELECT AVG(
                (strftime('%s', s.completed_at) - strftime('%s', s.checked_in_at)) / 60.0
            ) as avg_minutes
            FROM sessions s
            JOIN bookings b ON s.booking_id = b.id
            WHERE DATE(b.start_time) = ?
            AND s.completed_at IS NOT NULL
            AND s.checked_in_at IS NOT NULL
        """, (date,))
        row = cursor.fetchone()
        avg_minutes = round(row["avg_minutes"], 1) if row["avg_minutes"] else None

        # --- Busiest hour (by check-in time) ---
        cursor.execute("""
            SELECT strftime('%H:00', s.checked_in_at) as hour, COUNT(*) as checkins
            FROM sessions s
            JOIN bookings b ON s.booking_id = b.id
            WHERE DATE(b.start_time) = ?
            GROUP BY hour
            ORDER BY checkins DESC
            LIMIT 1
        """, (date,))
        busiest = cursor.fetchone()
        busiest_hour = dict(busiest) if busiest else None

        # --- Per-booth breakdown ---
        cursor.execute("""
            SELECT
                bo.name as booth_name,
                bo.location,
                COUNT(bk.id) as total_bookings,
                SUM(CASE WHEN bk.status = 'completed'  THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN bk.status = 'cancelled'  THEN 1 ELSE 0 END) as cancelled,
                SUM(CASE WHEN bk.status = 'interrupted' THEN 1 ELSE 0 END) as interrupted
            FROM booths bo
            LEFT JOIN bookings bk
                ON bo.id = bk.booth_id AND DATE(bk.start_time) = ?
            GROUP BY bo.id
            ORDER BY bo.name
        """, (date,))
        booth_rows = cursor.fetchall()
        utilization_by_booth = [dict(r) for r in booth_rows]

        # --- No-show rate ---
        # A no-show = session was scheduled, start_time has passed, but no check-in
        cursor.execute("""
            SELECT COUNT(*) as no_shows FROM bookings
            WHERE DATE(start_time) = ?
            AND status = 'scheduled'
            AND end_time < datetime('now')
        """, (date,))
        no_shows = cursor.fetchone()["no_shows"]

        # --- Utilization rate ---
        active = counts["total"] - counts["cancelled"]
        utilization_rate = (
            round(counts["completed"] / active * 100, 1) if active > 0 else 0
        )

        return {
            "date": date,
            "total_bookings": counts["total"],
            "completed": counts["completed"],
            "cancelled": counts["cancelled"],
            "interrupted": counts["interrupted"],
            "no_shows": no_shows,
            "avg_session_minutes": avg_minutes,
            "busiest_hour": busiest_hour,
            "utilization_rate_pct": utilization_rate,
            "utilization_by_booth": utilization_by_booth,
        }

    finally:
        conn.close()


def get_audit_trail(booking_id=None, date=None, limit=500):
    """
    Fetch audit log entries. Can filter by booking_id or date.
    Returns list of dicts ordered by most recent first.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()

        query = "SELECT * FROM audit_log WHERE 1=1"
        params = []

        if booking_id:
            query += " AND booking_id = ?"
            params.append(booking_id)

        if date:
            query += " AND DATE(occurred_at) = ?"
            params.append(date)

        query += " ORDER BY occurred_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [dict(r) for r in rows]

    finally:
        conn.close()


def export_audit_csv(booking_id=None, date=None):
    """
    Export audit trail as a CSV string.
    Can be used to stream a file download from Flask.
    """
    entries = get_audit_trail(booking_id=booking_id, date=date)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "id", "event_type", "booking_id", "booth_id", "actor", "detail", "occurred_at"
    ])
    writer.writeheader()
    writer.writerows(entries)

    return output.getvalue()


def _today():
    from utils import now_str
    return now_str()[:10]
