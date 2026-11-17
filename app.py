from flask import Flask, request, jsonify, Response, render_template
from bookings import (
    create_booking,
    checkin,
    cancel_booking,
    complete_session,
    get_available_booths,
    get_booking,
    get_all_bookings_today,
    BookingConflictError,
    BookingNotFoundError,
    InvalidCheckinError,
    CancellationNotAllowedError,
)
from analytics import get_utilization_stats, get_audit_trail, export_audit_csv
from db import init_db

app = Flask(__name__)
init_db()


# ── Bookings ──────────────────────────────────────────────────────────────────

@app.route("/bookings", methods=["POST"])
def book():
    """
    Create a new booth booking.

    Body (JSON):
        booth_id, candidate_name, candidate_email,
        interviewer_name, start_time, end_time
        (times in format: "YYYY-MM-DD HH:MM")

    Returns checkin_code on success.
    Returns 409 if the slot overlaps an existing booking.
    """
    data = request.get_json()
    required = ["booth_id", "candidate_name", "candidate_email",
                "interviewer_name", "start_time", "end_time"]

    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    try:
        result = create_booking(
            booth_id=data["booth_id"],
            candidate_name=data["candidate_name"],
            candidate_email=data["candidate_email"],
            interviewer_name=data["interviewer_name"],
            start_time=data["start_time"],
            end_time=data["end_time"],
        )
        return jsonify(result), 201

    except BookingConflictError as e:
        return jsonify({"error": str(e)}), 409


@app.route("/bookings/<int:booking_id>", methods=["GET"])
def get_booking_route(booking_id):
    """Fetch a booking and its session status."""
    try:
        return jsonify(get_booking(booking_id)), 200
    except BookingNotFoundError as e:
        return jsonify({"error": str(e)}), 404


@app.route("/bookings/<int:booking_id>", methods=["DELETE"])
def cancel(booking_id):
    """Cancel a scheduled booking (not allowed after check-in)."""
    try:
        return jsonify(cancel_booking(booking_id)), 200
    except BookingNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except CancellationNotAllowedError as e:
        return jsonify({"error": str(e)}), 409


@app.route("/bookings/<int:booking_id>/complete", methods=["POST"])
def complete(booking_id):
    """Mark a session as completed."""
    data = request.get_json() or {}
    try:
        return jsonify(complete_session(booking_id, notes=data.get("notes", ""))), 200
    except BookingNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except InvalidCheckinError as e:
        return jsonify({"error": str(e)}), 409


# ── Check-in ──────────────────────────────────────────────────────────────────

@app.route("/checkin", methods=["POST"])
def checkin_route():
    """
    Validate a check-in code and begin the interview session.

    Body (JSON): { "code": "ABC123" }

    Returns 200 on success.
    Returns 400 for invalid/already-used codes.
    """
    data = request.get_json()
    code = data.get("code", "").strip().upper()

    if not code:
        return jsonify({"error": "Check-in code is required."}), 400

    try:
        return jsonify(checkin(code)), 200
    except InvalidCheckinError as e:
        return jsonify({"error": str(e)}), 400


# ── Booth Availability ────────────────────────────────────────────────────────

@app.route("/booths/available", methods=["GET"])
def available():
    """
    List booths with no bookings in the requested time window.

    Query params: start_time, end_time (format: "YYYY-MM-DD HH:MM")
    """
    start = request.args.get("start_time")
    end = request.args.get("end_time")

    if not start or not end:
        return jsonify({"error": "start_time and end_time are required."}), 400

    booths = get_available_booths(start, end)
    return jsonify({"available_booths": booths, "count": len(booths)}), 200


# ── Analytics ─────────────────────────────────────────────────────────────────

@app.route("/analytics", methods=["GET"])
def analytics():
    """
    Utilization analytics for a given date.

    Query param: date (YYYY-MM-DD, defaults to today)

    Returns:
    - total bookings, completed, cancelled, no-shows
    - avg session duration in minutes
    - busiest hour
    - utilization rate %
    - per-booth breakdown
    """
    date = request.args.get("date")
    stats = get_utilization_stats(date=date)
    return jsonify(stats), 200


# ── Audit Trail ───────────────────────────────────────────────────────────────

@app.route("/audit", methods=["GET"])
def audit():
    """
    Fetch the audit trail as JSON or download as CSV.

    Query params:
    - booking_id  (optional) filter by booking
    - date        (optional) filter by date YYYY-MM-DD
    - format      "csv" to download, default is JSON
    """
    booking_id = request.args.get("booking_id", type=int)
    date = request.args.get("date")
    fmt = request.args.get("format", "json")

    if fmt == "csv":
        csv_data = export_audit_csv(booking_id=booking_id, date=date)
        filename = f"audit_{date or 'all'}.csv"
        return Response(
            csv_data,
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    entries = get_audit_trail(booking_id=booking_id, date=date)
    return jsonify({"count": len(entries), "entries": entries}), 200


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.route("/dashboard", methods=["GET"])
def dashboard():
    """HTML dashboard showing today's booth schedule and live status."""
    bookings = get_all_bookings_today()
    stats = get_utilization_stats()
    return render_template("dashboard.html", bookings=bookings, stats=stats)


# ── Health check ──────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "BoothOps"}), 200


if __name__ == "__main__":
    app.run(debug=True, port=5001)
