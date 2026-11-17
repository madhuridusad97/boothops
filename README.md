# BoothOps

Booth scheduling, check-in, and session reliability software for physical technical interview infrastructure.

Built as an exploratory prototype inspired by [Airlock](https://www.airlock.so) — a startup building trusted in-person technical interview environments.

---

## The Problem

Technical hiring depends on trust: employers need confidence that the person they're evaluating is who they claim to be, working in a fair, standardized environment. Physical interview booths solve the environmental trust problem — but they create a new operational challenge.

**Without reliable booth management software:**
- Double-bookings disrupt candidate and interviewer schedules
- No-shows leave booths idle with no recovery mechanism
- Operators have no real-time visibility into booth status
- There is no audit trail if a dispute arises post-interview

BoothOps is the software layer that makes the physical booth infrastructure reliable.

---

## Who Uses This

| User | Need |
|---|---|
| **Recruiter** | Book a booth for a specific candidate + interviewer, get a check-in code |
| **Candidate** | Arrive at booth, enter code, begin session |
| **Booth Operator** | Monitor all sessions in real time, handle issues |
| **Hiring Manager** | Review session audit trail, download compliance export |
| **Airlock Admin** | Analyze utilization across all booths, identify peak hours |

---

## Core Use Cases

**UC1 — Standard booking flow**
Recruiter books Booth A for Alice Chen with interviewer Mrenaal Mirpuri at 10:00–10:45. System generates check-in code `ABC123`. Alice arrives, enters code, session begins. Interviewer marks complete. Full audit trail written.

**UC2 — Conflict prevention**
Two recruiters simultaneously try to book Booth A at 10:00. Only one succeeds. The second receives a 409 Conflict with an explanation. No silent failures, no double-booking.

**UC3 — Cancellation + rebooking**
Candidate cancels 2 hours before. Booth A is immediately available for rebooking. Cancelled bookings are excluded from conflict checks.

**UC4 — No-show detection**
Candidate never checks in. 10 minutes past start time, the slot appears in analytics as a no-show. Booth is freed for emergency rebooking.

**UC5 — Career fair (multi-booking)**
University hosts 5 employers across 3 booths. Each employer books separate time slots. Operators see the full daily schedule on the dashboard. At end of day, compliance team exports the audit trail as CSV.

**UC6 — Compliance audit**
Post-interview dispute: "Was the correct candidate in the booth?" Hiring manager pulls `/audit?booking_id=42&format=csv` — gets an immutable log of every event: who booked, what code was used, exact check-in time, session completion, any notes.

---

## Competitive Analysis

| Solution | Gap vs BoothOps |
|---|---|
| **Calendly / Google Calendar** | General-purpose scheduling. No concept of physical booths, no check-in flow, no session state machine, no audit trail |
| **HireVue / CoderPad** | Virtual-only. Doesn't map to physical spaces or identity verification at a booth door |
| **Proctoring software (ProctorU, Honorlock)** | Surveillance-heavy, candidate-adversarial, no booth logistics |
| **Pearson VUE / Prometric** | Certification exams, not engineering hiring. Expensive, closed infrastructure |
| **Manual spreadsheets** | No conflict prevention, no real-time status, no audit trail, breaks at any scale |
| **Custom internal tools** | High build cost, no standardization across employers |

**BoothOps differentiator:** purpose-built for physical interview booths — combines scheduling, real-time status, identity check-in, and immutable audit in one system.

---

## Technical Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Flask REST API                       │
│  /bookings  /checkin  /analytics  /audit  /dashboard    │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│                   Business Logic Layer                   │
│         bookings.py          analytics.py               │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│                      SQLite (db.py)                      │
│   booths │ bookings │ sessions │ audit_log               │
└─────────────────────────────────────────────────────────┘
```

**Key technical decisions:**

1. **Overlap detection via SQL transaction** — the conflict check and INSERT are atomic. Even under concurrent requests, two bookings cannot occupy the same booth at the same time.

   ```sql
   SELECT COUNT(*) FROM bookings
   WHERE booth_id = ? AND status NOT IN ('cancelled','interrupted')
   AND start_time < ? AND end_time > ?
   ```
   Overlap condition: interval [A,B) overlaps [C,D) when `A < D AND B > C`.

2. **Audit log written inside the same transaction** — the log entry and the state change are atomic. You can never have a check-in without a log entry, or a log entry for a check-in that didn't happen.

3. **Status state machine** — bookings move through defined states only:
   `scheduled → checked_in → in_progress → completed`
   with exits to `cancelled` (pre-check-in) or `interrupted` (mid-session).
   Invalid transitions raise exceptions, never silently corrupt state.

4. **SQLite + WAL mode** — `PRAGMA journal_mode=WAL` allows concurrent reads without blocking writes. Sufficient for a prototype; production would migrate to PostgreSQL with row-level locking.

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/bookings` | Create a booking, returns check-in code |
| `GET` | `/bookings/:id` | Fetch booking + session status |
| `DELETE` | `/bookings/:id` | Cancel (only if not yet checked in) |
| `POST` | `/bookings/:id/complete` | Mark session completed |
| `POST` | `/checkin` | Validate code, begin session |
| `GET` | `/booths/available` | List free booths for a time window |
| `GET` | `/analytics` | Utilization stats for a date |
| `GET` | `/audit` | Audit trail (JSON or CSV export) |
| `GET` | `/dashboard` | HTML operator view |
| `GET` | `/health` | Service health check |

---

## Setup & Run

```bash
git clone <repo>
cd boothops
pip install flask
python seed.py        # creates DB + sample data
python app.py         # starts on http://localhost:5001
```

Open `http://localhost:5001/dashboard` to see the live operator view.

---

## Tests

```bash
python -m pytest tests/ -v
```

**23 tests covering:**
- Booking creation and conflict prevention
- Boundary conditions (adjacent slots, different booths)
- Check-in flow (valid, invalid, duplicate)
- Cancellation rules
- Audit trail completeness
- Analytics accuracy and utilization rate calculation

---

## Product Roadmap

What I'd prioritize next if this were a real product:

| Priority | Feature | Why |
|---|---|---|
| P0 | **ATS Integration** (Greenhouse, Lever) | No recruiter adopts a new tool that doesn't connect to their existing workflow. This is the enterprise sales unlock. |
| P0 | **Identity Verification** | Camera match at check-in against submitted ID. Core to Airlock's trust mission — confirms the person interviewing is who they claimed to be. |
| P1 | **Real-time booth status** (WebSocket) | Operators need live updates, not page refreshes. |
| P1 | **SMS/email check-in code delivery** | Reduces no-show friction. Candidate shouldn't need to remember a code. |
| P2 | **Waitlist management** | Auto-notify next candidate when a slot cancels. Maximizes booth utilization. |
| P2 | **Interviewer scorecard** | Structured rubric filled in immediately post-session. Syncs to ATS. |
| P3 | **Multi-employer career fair mode** | Shared booth pool, isolated per-employer data. High value for university partnerships. |
| P3 | **No-show prediction** | Flag high-risk bookings proactively so recruiters can follow up before it's too late. |

---

## About This Project

Built in 3 days as a technical exploration of the engineering challenges behind physical interview booth infrastructure. Focus was on correctness (conflict prevention, audit atomicity) over completeness.

**Author:** Madhuri Kishor Dusad — [linkedin.com/in/madhuridusad1997](https://linkedin.com/in/madhuridusad1997)
