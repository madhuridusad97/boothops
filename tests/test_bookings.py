"""
BoothOps Test Suite

Covers:
- Core booking logic (create, conflict, cancel)
- Check-in flow (valid, invalid, duplicate)
- Audit trail integrity
- Analytics correctness
- Edge cases (boundary times, missing fields)
"""

import sys
import os
import unittest
import tempfile

# Add parent directory to path so we can import our modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db as db_module
from db import init_db
from bookings import (
    create_booking,
    checkin,
    cancel_booking,
    complete_session,
    get_available_booths,
    get_booking,
    BookingConflictError,
    BookingNotFoundError,
    InvalidCheckinError,
    CancellationNotAllowedError,
)
from analytics import get_utilization_stats, get_audit_trail, export_audit_csv


def _seed_booths():
    """Insert 3 test booths. Returns their IDs."""
    conn = db_module.get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO booths (name, location) VALUES ('Booth A', 'Room 101')")
    cursor.execute("INSERT INTO booths (name, location) VALUES ('Booth B', 'Room 102')")
    cursor.execute("INSERT INTO booths (name, location) VALUES ('Booth C', 'Room 103')")
    conn.commit()
    conn.close()


class TestBoothOps(unittest.TestCase):

    def setUp(self):
        """
        Each test gets a fresh temporary database.
        We patch DB_PATH in the db module so all code uses the temp file.
        """
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        db_module.DB_PATH = self.tmp.name
        init_db()
        _seed_booths()

    def tearDown(self):
        os.unlink(self.tmp.name)

    # ── 1. Create booking ──────────────────────────────────────────────────────

    def test_create_booking_success(self):
        """A valid booking returns a booking_id and a 6-char check-in code."""
        result = create_booking(
            booth_id=1,
            candidate_name="Alice Chen",
            candidate_email="alice@test.com",
            interviewer_name="Mrenaal Mirpuri",
            start_time="2026-11-21 10:00",
            end_time="2026-11-21 10:45",
        )
        self.assertIn("booking_id", result)
        self.assertIn("checkin_code", result)
        self.assertEqual(result["status"], "scheduled")
        self.assertEqual(len(result["checkin_code"]), 6)

    # ── 2. Overlap prevention ──────────────────────────────────────────────────

    def test_overlapping_booking_raises_conflict(self):
        """
        A second booking on the same booth that overlaps in time must be rejected.
        This is the core correctness guarantee of BoothOps.
        """
        create_booking(1, "Alice", "alice@test.com", "Interviewer",
                       "2026-11-21 10:00", "2026-11-21 10:45")

        with self.assertRaises(BookingConflictError):
            create_booking(1, "Bob", "bob@test.com", "Interviewer",
                           "2026-11-21 10:15", "2026-11-21 11:00")  # overlaps

    def test_partial_overlap_at_start_raises_conflict(self):
        """Booking that starts before existing slot ends must be rejected."""
        create_booking(1, "Alice", "alice@test.com", "Interviewer",
                       "2026-11-21 10:00", "2026-11-21 10:45")

        with self.assertRaises(BookingConflictError):
            create_booking(1, "Bob", "bob@test.com", "Interviewer",
                           "2026-11-21 09:30", "2026-11-21 10:15")

    def test_adjacent_slots_do_not_conflict(self):
        """
        Back-to-back bookings (one ends exactly when next starts) must NOT conflict.
        Boundary condition: [10:00–10:45] and [10:45–11:30] are adjacent, not overlapping.
        """
        create_booking(1, "Alice", "alice@test.com", "Interviewer",
                       "2026-11-21 10:00", "2026-11-21 10:45")
        # Should succeed — no overlap
        result = create_booking(1, "Bob", "bob@test.com", "Interviewer",
                                "2026-11-21 10:45", "2026-11-21 11:30")
        self.assertEqual(result["status"], "scheduled")

    def test_different_booth_same_time_allowed(self):
        """Two different booths can be booked for the exact same time slot."""
        create_booking(1, "Alice", "alice@test.com", "Interviewer",
                       "2026-11-21 10:00", "2026-11-21 10:45")
        result = create_booking(2, "Bob", "bob@test.com", "Interviewer",
                                "2026-11-21 10:00", "2026-11-21 10:45")
        self.assertEqual(result["status"], "scheduled")

    def test_cancelled_slot_can_be_rebooked(self):
        """After cancellation, the same slot on the same booth is available again."""
        b = create_booking(1, "Alice", "alice@test.com", "Interviewer",
                           "2026-11-21 10:00", "2026-11-21 10:45")
        cancel_booking(b["booking_id"])

        result = create_booking(1, "Carol", "carol@test.com", "Interviewer",
                                "2026-11-21 10:00", "2026-11-21 10:45")
        self.assertEqual(result["status"], "scheduled")

    # ── 3. Check-in ───────────────────────────────────────────────────────────

    def test_checkin_with_valid_code(self):
        """Check-in with the correct code transitions status to checked_in."""
        b = create_booking(1, "Alice", "alice@test.com", "Interviewer",
                           "2026-11-21 10:00", "2026-11-21 10:45")
        result = checkin(b["checkin_code"])
        self.assertEqual(result["status"], "checked_in")
        self.assertEqual(result["candidate_name"], "Alice")

    def test_checkin_with_invalid_code_fails(self):
        """A made-up code must raise InvalidCheckinError — no silent failure."""
        with self.assertRaises(InvalidCheckinError):
            checkin("XXXXXX")

    def test_duplicate_checkin_raises_error(self):
        """Checking in twice with the same code must be rejected."""
        b = create_booking(1, "Alice", "alice@test.com", "Interviewer",
                           "2026-11-21 10:00", "2026-11-21 10:45")
        checkin(b["checkin_code"])

        with self.assertRaises(InvalidCheckinError):
            checkin(b["checkin_code"])

    # ── 4. Cancellation ───────────────────────────────────────────────────────

    def test_cancel_scheduled_booking_succeeds(self):
        """A booking in 'scheduled' state can be cancelled."""
        b = create_booking(1, "Alice", "alice@test.com", "Interviewer",
                           "2026-11-21 10:00", "2026-11-21 10:45")
        result = cancel_booking(b["booking_id"])
        self.assertEqual(result["status"], "cancelled")

    def test_cancel_checked_in_booking_fails(self):
        """
        Cannot cancel once a candidate has checked in.
        The session is live — cancellation would corrupt the audit trail.
        """
        b = create_booking(1, "Alice", "alice@test.com", "Interviewer",
                           "2026-11-21 10:00", "2026-11-21 10:45")
        checkin(b["checkin_code"])

        with self.assertRaises(CancellationNotAllowedError):
            cancel_booking(b["booking_id"])

    def test_cancel_nonexistent_booking_raises_not_found(self):
        with self.assertRaises(BookingNotFoundError):
            cancel_booking(99999)

    # ── 5. Session completion ─────────────────────────────────────────────────

    def test_complete_session_success(self):
        """A checked-in session can be marked completed with optional notes."""
        b = create_booking(1, "Alice", "alice@test.com", "Interviewer",
                           "2026-11-21 10:00", "2026-11-21 10:45")
        checkin(b["checkin_code"])
        result = complete_session(b["booking_id"], notes="Strong candidate.")
        self.assertEqual(result["status"], "completed")

    def test_complete_unchecked_session_fails(self):
        """Cannot complete a session that was never checked in."""
        b = create_booking(1, "Alice", "alice@test.com", "Interviewer",
                           "2026-11-21 10:00", "2026-11-21 10:45")
        with self.assertRaises(InvalidCheckinError):
            complete_session(b["booking_id"])

    # ── 6. Available booths ───────────────────────────────────────────────────

    def test_available_booths_excludes_booked(self):
        """Booths with active bookings in the window must not appear as available."""
        create_booking(1, "Alice", "alice@test.com", "Interviewer",
                       "2026-11-21 10:00", "2026-11-21 10:45")
        available = get_available_booths("2026-11-21 10:00", "2026-11-21 10:45")
        booth_ids = [b["id"] for b in available]
        self.assertNotIn(1, booth_ids)
        self.assertIn(2, booth_ids)
        self.assertIn(3, booth_ids)

    def test_available_booths_includes_cancelled(self):
        """A booth whose only booking was cancelled must appear as available."""
        b = create_booking(1, "Alice", "alice@test.com", "Interviewer",
                           "2026-11-21 10:00", "2026-11-21 10:45")
        cancel_booking(b["booking_id"])
        available = get_available_booths("2026-11-21 10:00", "2026-11-21 10:45")
        booth_ids = [b["id"] for b in available]
        self.assertIn(1, booth_ids)

    # ── 7. Audit trail ────────────────────────────────────────────────────────

    def test_audit_trail_records_booking_creation(self):
        """Creating a booking must write a booking_created audit entry."""
        b = create_booking(1, "Alice", "alice@test.com", "Interviewer",
                           "2026-11-21 10:00", "2026-11-21 10:45")
        entries = get_audit_trail(booking_id=b["booking_id"])
        event_types = [e["event_type"] for e in entries]
        self.assertIn("booking_created", event_types)

    def test_audit_trail_records_full_lifecycle(self):
        """
        A complete booking lifecycle must produce exactly 3 audit entries:
        booking_created → candidate_checked_in → session_completed.
        """
        b = create_booking(1, "Alice", "alice@test.com", "Interviewer",
                           "2026-11-21 10:00", "2026-11-21 10:45")
        checkin(b["checkin_code"])
        complete_session(b["booking_id"], notes="Good session.")

        entries = get_audit_trail(booking_id=b["booking_id"])
        event_types = [e["event_type"] for e in entries]

        self.assertIn("booking_created", event_types)
        self.assertIn("candidate_checked_in", event_types)
        self.assertIn("session_completed", event_types)
        self.assertEqual(len(entries), 3)

    def test_audit_trail_records_cancellation(self):
        """Cancelling a booking must write a booking_cancelled audit entry."""
        b = create_booking(1, "Alice", "alice@test.com", "Interviewer",
                           "2026-11-21 10:00", "2026-11-21 10:45")
        cancel_booking(b["booking_id"])
        entries = get_audit_trail(booking_id=b["booking_id"])
        event_types = [e["event_type"] for e in entries]
        self.assertIn("booking_cancelled", event_types)

    def test_audit_csv_export_contains_headers(self):
        """CSV export must include standard column headers."""
        b = create_booking(1, "Alice", "alice@test.com", "Interviewer",
                           "2026-11-21 10:00", "2026-11-21 10:45")
        csv_output = export_audit_csv(booking_id=b["booking_id"])
        self.assertIn("event_type", csv_output)
        self.assertIn("booking_id", csv_output)
        self.assertIn("occurred_at", csv_output)
        self.assertIn("booking_created", csv_output)

    # ── 8. Analytics ──────────────────────────────────────────────────────────

    def test_analytics_counts_completed_correctly(self):
        """Analytics must count completed sessions accurately."""
        b1 = create_booking(1, "Alice", "alice@test.com", "Interviewer",
                            "2026-11-21 10:00", "2026-11-21 10:45")
        checkin(b1["checkin_code"])
        complete_session(b1["booking_id"])

        b2 = create_booking(2, "Bob", "bob@test.com", "Interviewer",
                            "2026-11-21 11:00", "2026-11-21 11:45")
        checkin(b2["checkin_code"])
        # Bob's session not completed

        stats = get_utilization_stats(date="2026-11-21")
        self.assertEqual(stats["completed"], 1)
        self.assertEqual(stats["total_bookings"], 2)

    def test_analytics_utilization_rate(self):
        """Utilization rate = completed / (total - cancelled) * 100."""
        b1 = create_booking(1, "Alice", "alice@test.com", "Interviewer",
                            "2026-11-21 10:00", "2026-11-21 10:45")
        checkin(b1["checkin_code"])
        complete_session(b1["booking_id"])

        b2 = create_booking(2, "Bob", "bob@test.com", "Interviewer",
                            "2026-11-21 11:00", "2026-11-21 11:45")
        cancel_booking(b2["booking_id"])  # cancelled doesn't count in denominator

        stats = get_utilization_stats(date="2026-11-21")
        # 1 completed out of 1 active (Bob cancelled) = 100%
        self.assertEqual(stats["utilization_rate_pct"], 100.0)

    def test_analytics_per_booth_breakdown(self):
        """Per-booth analytics must include all booths, even ones with no bookings."""
        create_booking(1, "Alice", "alice@test.com", "Interviewer",
                       "2026-11-21 10:00", "2026-11-21 10:45")
        stats = get_utilization_stats(date="2026-11-21")
        booth_names = [b["booth_name"] for b in stats["utilization_by_booth"]]
        self.assertIn("Booth A", booth_names)
        self.assertIn("Booth B", booth_names)
        self.assertIn("Booth C", booth_names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
