import random
import string
from datetime import datetime


def generate_checkin_code(length=6):
    """Generate a unique alphanumeric check-in code, e.g. 'A3X9KQ'"""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def parse_time(time_str):
    """Parse time string to datetime object for comparison."""
    return datetime.strptime(time_str, "%Y-%m-%d %H:%M")


def format_booking(row):
    """Convert a sqlite3.Row booking into a plain dict."""
    return {
        "id": row["id"],
        "booth_id": row["booth_id"],
        "candidate_name": row["candidate_name"],
        "candidate_email": row["candidate_email"],
        "interviewer_name": row["interviewer_name"],
        "start_time": row["start_time"],
        "end_time": row["end_time"],
        "checkin_code": row["checkin_code"],
        "status": row["status"],
        "created_at": row["created_at"],
    }
