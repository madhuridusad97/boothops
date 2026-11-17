from db import get_connection, audit_event
from utils import generate_checkin_code, now_str, format_booking


class BookingConflictError(Exception):
    pass


class BookingNotFoundError(Exception):
    pass


class InvalidCheckinError(Exception):
    pass


class CancellationNotAllowedError(Exception):
    pass


def create_booking(booth_id, candidate_name, candidate_email, interviewer_name, start_time, end_time):
    """
    Reserve a booth for a time slot.

    Uses a transaction + overlap query to guarantee no two bookings
    can occupy the same booth at the same time — even under concurrent requests.

    Overlap condition: two intervals [A,B) and [C,D) overlap when A < D AND B > C.
    We exclude cancelled and interrupted bookings from the conflict check.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()

        # Check for overlapping bookings within a transaction
        cursor.execute("""
            SELECT COUNT(*) FROM bookings
            WHERE booth_id = ?
            AND status NOT IN ('cancelled', 'interrupted')
            AND start_time < ?
            AND end_time > ?
        """, (booth_id, end_time, start_time))

        if cursor.fetchone()[0] > 0:
            raise BookingConflictError(
                f"Booth {booth_id} is already booked between {start_time} and {end_time}."
            )

        code = generate_checkin_code()

        cursor.execute("""
            INSERT INTO bookings
                (booth_id, candidate_name, candidate_email, interviewer_name,
                 start_time, end_time, checkin_code, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'scheduled', ?)
        """, (booth_id, candidate_name, candidate_email, interviewer_name,
              start_time, end_time, code, now_str()))

        booking_id = cursor.lastrowid

        audit_event(conn,
            event_type="booking_created",
            booking_id=booking_id,
            booth_id=booth_id,
            actor=candidate_email,
            detail=f"Booked by {candidate_name} with {interviewer_name} from {start_time} to {end_time}"
        )

        conn.commit()

        return {
            "booking_id": booking_id,
            "checkin_code": code,
            "status": "scheduled",
            "message": f"Booking confirmed. Check-in code: {code}"
        }

    except BookingConflictError:
        conn.rollback()
        raise
    finally:
        conn.close()


def checkin(checkin_code):
    """
    Validate a check-in code and transition booking to 'checked_in'.

    Prevents duplicate check-ins — if already checked in, raises InvalidCheckinError.
    Creates a session record to track the interview lifecycle.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM bookings WHERE checkin_code = ?
        """, (checkin_code,))
        booking = cursor.fetchone()

        if not booking:
            raise InvalidCheckinError("Invalid check-in code.")

        if booking["status"] == "checked_in" or booking["status"] == "in_progress":
            raise InvalidCheckinError("Candidate has already checked in.")

        if booking["status"] in ("cancelled", "completed", "interrupted"):
            raise InvalidCheckinError(
                f"Cannot check in — booking status is '{booking['status']}'."
            )

        cursor.execute("""
            UPDATE bookings SET status = 'checked_in' WHERE id = ?
        """, (booking["id"],))

        cursor.execute("""
            INSERT OR IGNORE INTO sessions (booking_id, checked_in_at)
            VALUES (?, ?)
        """, (booking["id"], now_str()))

        audit_event(conn,
            event_type="candidate_checked_in",
            booking_id=booking["id"],
            booth_id=booking["booth_id"],
            actor=booking["candidate_email"],
            detail=f"{booking['candidate_name']} checked in using code {checkin_code}"
        )

        conn.commit()

        return {
            "booking_id": booking["id"],
            "candidate_name": booking["candidate_name"],
            "booth_id": booking["booth_id"],
            "status": "checked_in",
            "message": "Check-in successful. Interview session started."
        }

    except (InvalidCheckinError, BookingNotFoundError):
        conn.rollback()
        raise
    finally:
        conn.close()


def complete_session(booking_id, notes=""):
    """Mark an interview session as completed."""
    conn = get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,))
        booking = cursor.fetchone()

        if not booking:
            raise BookingNotFoundError(f"Booking {booking_id} not found.")

        if booking["status"] not in ("checked_in", "in_progress"):
            raise InvalidCheckinError(
                f"Cannot complete — booking status is '{booking['status']}'."
            )

        cursor.execute("""
            UPDATE bookings SET status = 'completed' WHERE id = ?
        """, (booking_id,))

        cursor.execute("""
            UPDATE sessions SET completed_at = ?, notes = ?
            WHERE booking_id = ?
        """, (now_str(), notes, booking_id))

        audit_event(conn,
            event_type="session_completed",
            booking_id=booking_id,
            booth_id=booking["booth_id"],
            actor="system",
            detail=f"Session completed. Notes: {notes or 'none'}"
        )

        conn.commit()
        return {"booking_id": booking_id, "status": "completed"}

    finally:
        conn.close()


def cancel_booking(booking_id):
    """
    Cancel a booking — only allowed if it hasn't been checked in yet.
    Once a candidate checks in, the session is live and cannot be cancelled.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,))
        booking = cursor.fetchone()

        if not booking:
            raise BookingNotFoundError(f"Booking {booking_id} not found.")

        if booking["status"] != "scheduled":
            raise CancellationNotAllowedError(
                f"Cannot cancel — booking is already '{booking['status']}'."
            )

        cursor.execute("""
            UPDATE bookings SET status = 'cancelled' WHERE id = ?
        """, (booking_id,))

        audit_event(conn,
            event_type="booking_cancelled",
            booking_id=booking_id,
            booth_id=booking["booth_id"],
            actor="operator",
            detail=f"Booking for {booking['candidate_name']} cancelled before check-in"
        )

        conn.commit()
        return {"booking_id": booking_id, "status": "cancelled", "message": "Booking cancelled."}

    finally:
        conn.close()


def get_available_booths(start_time, end_time):
    """
    Return all booths that have no active booking in the requested window.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM booths
            WHERE id NOT IN (
                SELECT booth_id FROM bookings
                WHERE status NOT IN ('cancelled', 'interrupted')
                AND start_time < ?
                AND end_time > ?
            )
        """, (end_time, start_time))

        booths = cursor.fetchall()
        return [{"id": b["id"], "name": b["name"], "location": b["location"]} for b in booths]

    finally:
        conn.close()


def get_booking(booking_id):
    """Fetch a single booking with its session info."""
    conn = get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,))
        booking = cursor.fetchone()

        if not booking:
            raise BookingNotFoundError(f"Booking {booking_id} not found.")

        cursor.execute("SELECT * FROM sessions WHERE booking_id = ?", (booking_id,))
        session = cursor.fetchone()

        result = format_booking(booking)
        result["session"] = dict(session) if session else None
        return result

    finally:
        conn.close()


def get_all_bookings_today():
    """Fetch all bookings for today — used by the dashboard."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        today = now_str()[:10]  # "YYYY-MM-DD"

        cursor.execute("""
            SELECT b.*, bo.name as booth_name, bo.location
            FROM bookings b
            JOIN booths bo ON b.booth_id = bo.id
            WHERE DATE(b.start_time) = ?
            ORDER BY b.start_time ASC
        """, (today,))

        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    finally:
        conn.close()
