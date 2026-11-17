from db import get_connection, init_db


def seed():
    init_db()
    conn = get_connection()
    cursor = conn.cursor()

    # Clear existing data
    cursor.execute("DELETE FROM sessions")
    cursor.execute("DELETE FROM bookings")
    cursor.execute("DELETE FROM booths")

    # Seed booths
    booths = [
        ("Booth A", "CMU Silicon Valley - Room 101"),
        ("Booth B", "CMU Silicon Valley - Room 102"),
        ("Booth C", "CMU Silicon Valley - Room 103"),
    ]
    cursor.executemany("INSERT INTO booths (name, location) VALUES (?, ?)", booths)

    # Seed sample bookings for today
    from utils import now_str
    today = now_str()[:10]

    sample_bookings = [
        (1, "Alice Chen", "alice@example.com", "Mrenaal Mirpuri", f"{today} 09:00", f"{today} 09:45", "ABC123"),
        (2, "Bob Smith", "bob@example.com", "Sarah Johnson", f"{today} 10:00", f"{today} 10:45", "DEF456"),
        (1, "Carol Davis", "carol@example.com", "Mrenaal Mirpuri", f"{today} 11:00", f"{today} 11:45", "GHI789"),
        (3, "David Park", "david@example.com", "Tom Wilson", f"{today} 09:30", f"{today} 10:15", "JKL012"),
    ]

    cursor.executemany("""
        INSERT INTO bookings
            (booth_id, candidate_name, candidate_email, interviewer_name,
             start_time, end_time, checkin_code, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'scheduled', datetime('now'))
    """, sample_bookings)

    conn.commit()
    conn.close()
    print("Seed data inserted: 3 booths, 4 sample bookings.")


if __name__ == "__main__":
    seed()
