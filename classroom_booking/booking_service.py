from __future__ import annotations

import calendar
import sqlite3
import uuid
from datetime import date, datetime, time, timedelta

from .db import log_action

DATETIME_FORMAT = "%Y-%m-%d %H:%M"
WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DEFAULT_CLOSED_WEEKDAYS = {5, 6}


def parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value.replace(second=0, microsecond=0)
    text = value.strip().replace("T", " ")
    for fmt in (DATETIME_FORMAT, "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError("Use datetime format YYYY-MM-DD HH:MM.")


def parse_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(value.strip())


def dt_to_db(value: datetime) -> str:
    return value.replace(second=0, microsecond=0).isoformat(timespec="minutes")


def db_to_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def require_admin(user: dict) -> None:
    if not user.get("is_admin"):
        raise PermissionError("Admin access is required.")


def list_rooms(conn: sqlite3.Connection, active_only: bool = True) -> list[sqlite3.Row]:
    sql = "SELECT * FROM rooms"
    if active_only:
        sql += " WHERE is_active = 1"
    sql += " ORDER BY name"
    return list(conn.execute(sql))


def get_room(conn: sqlite3.Connection, room_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone()


def get_room_by_name(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM rooms WHERE name = ? COLLATE NOCASE", (name.strip(),)).fetchone()


def create_room(
    conn: sqlite3.Connection,
    name: str,
    capacity: int,
    location: str,
    color: str,
    actor: dict,
) -> int:
    require_admin(actor)
    cur = conn.execute(
        """
        INSERT INTO rooms (name, capacity, location, color)
        VALUES (?, ?, ?, ?)
        """,
        (name.strip(), max(0, int(capacity)), location.strip(), color),
    )
    conn.commit()
    room_id = int(cur.lastrowid)
    log_action(conn, actor["id"], "create_room", "room", room_id, name)
    return room_id


def update_room(
    conn: sqlite3.Connection,
    room_id: int,
    name: str,
    capacity: int,
    location: str,
    color: str,
    is_active: bool,
    actor: dict,
) -> None:
    require_admin(actor)
    conn.execute(
        """
        UPDATE rooms
        SET name = ?, capacity = ?, location = ?, color = ?, is_active = ?
        WHERE id = ?
        """,
        (name.strip(), max(0, int(capacity)), location.strip(), color, int(is_active), room_id),
    )
    conn.commit()
    log_action(conn, actor["id"], "update_room", "room", room_id, name)


def list_holidays(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM holidays ORDER BY holiday_date"))


def get_closed_weekdays(conn: sqlite3.Connection) -> set[int]:
    row = conn.execute("SELECT value FROM app_settings WHERE key = 'closed_weekdays'").fetchone()
    if not row:
        return set(DEFAULT_CLOSED_WEEKDAYS)
    if not row["value"].strip():
        return set()
    try:
        weekdays = {int(value) for value in row["value"].split(",") if value.strip()}
    except ValueError:
        return set(DEFAULT_CLOSED_WEEKDAYS)
    return {weekday for weekday in weekdays if 0 <= weekday <= 6}


def set_closed_weekdays(conn: sqlite3.Connection, weekdays: set[int] | list[int], actor: dict) -> None:
    require_admin(actor)
    cleaned = sorted({int(weekday) for weekday in weekdays if 0 <= int(weekday) <= 6})
    conn.execute(
        """
        INSERT INTO app_settings (key, value, updated_at)
        VALUES ('closed_weekdays', ?, CURRENT_TIMESTAMP)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
        """,
        (",".join(str(weekday) for weekday in cleaned),),
    )
    conn.commit()
    log_action(conn, actor["id"], "set_closed_weekdays", "setting", None, ",".join(str(weekday) for weekday in cleaned))


def closed_dates_between(conn: sqlite3.Connection, start: datetime, end: datetime) -> set[str]:
    closed_weekdays = get_closed_weekdays(conn)
    if not closed_weekdays:
        return set()
    last = end.date() if end.time() != time(0, 0) else end.date() - timedelta(days=1)
    current = start.date()
    dates = set()
    while current <= last:
        if current.weekday() in closed_weekdays:
            dates.add(current.isoformat())
        current += timedelta(days=1)
    return dates


def format_closed_dates(dates: set[str]) -> str:
    labels = []
    for value in sorted(dates):
        parsed = date.fromisoformat(value)
        labels.append(f"{value} ({WEEKDAY_NAMES[parsed.weekday()]})")
    return ", ".join(labels)


def upsert_holiday(conn: sqlite3.Connection, holiday_date: date, name: str, actor: dict) -> None:
    require_admin(actor)
    conn.execute(
        """
        INSERT INTO holidays (holiday_date, name, created_by)
        VALUES (?, ?, ?)
        ON CONFLICT(holiday_date) DO UPDATE SET name = excluded.name
        """,
        (holiday_date.isoformat(), name.strip(), actor["id"]),
    )
    conn.commit()
    log_action(conn, actor["id"], "upsert_holiday", "holiday", None, holiday_date.isoformat())


def delete_holiday(conn: sqlite3.Connection, holiday_id: int, actor: dict) -> None:
    require_admin(actor)
    conn.execute("DELETE FROM holidays WHERE id = ?", (holiday_id,))
    conn.commit()
    log_action(conn, actor["id"], "delete_holiday", "holiday", holiday_id)


def holiday_dates_between(conn: sqlite3.Connection, start: datetime, end: datetime) -> set[str]:
    last = end.date() if end.time() != time(0, 0) else end.date() - timedelta(days=1)
    rows = conn.execute(
        """
        SELECT holiday_date FROM holidays
        WHERE holiday_date BETWEEN ? AND ?
        """,
        (start.date().isoformat(), last.isoformat()),
    ).fetchall()
    return {row["holiday_date"] for row in rows}


def validate_time_window(conn: sqlite3.Connection, start: datetime, end: datetime) -> None:
    if end <= start:
        raise ValueError("End time must be after start time.")
    holidays = holiday_dates_between(conn, start, end)
    if holidays:
        raise ValueError(f"Bookings are not allowed on holidays: {', '.join(sorted(holidays))}.")
    closed_dates = closed_dates_between(conn, start, end)
    if closed_dates:
        raise ValueError(f"Bookings are not allowed on closed days: {format_closed_dates(closed_dates)}.")


def find_conflicts(
    conn: sqlite3.Connection,
    room_id: int,
    start: datetime,
    end: datetime,
    exclude_booking_ids: set[int] | None = None,
) -> list[sqlite3.Row]:
    rows = list(
        conn.execute(
            """
            SELECT b.*, r.name AS room_name, u.username
            FROM bookings b
            JOIN rooms r ON r.id = b.room_id
            JOIN users u ON u.id = b.user_id
            WHERE b.status = 'active'
              AND b.room_id = ?
              AND b.start_ts < ?
              AND b.end_ts > ?
            ORDER BY b.start_ts
            """,
            (room_id, dt_to_db(end), dt_to_db(start)),
        )
    )
    if exclude_booking_ids:
        rows = [row for row in rows if int(row["id"]) not in exclude_booking_ids]
    return rows


def check_availability(
    conn: sqlite3.Connection,
    start_value: str | datetime,
    end_value: str | datetime,
    room_id: int | None = None,
    min_capacity: int = 0,
) -> list[dict]:
    start = parse_dt(start_value)
    end = parse_dt(end_value)
    validate_time_window(conn, start, end)
    rooms = [get_room(conn, room_id)] if room_id else list_rooms(conn)
    result = []
    for room in [room for room in rooms if room]:
        if room["capacity"] < (min_capacity or 0):
            continue
        conflicts = find_conflicts(conn, int(room["id"]), start, end)
        result.append(
            {
                "room_id": int(room["id"]),
                "room_name": room["name"],
                "capacity": int(room["capacity"]),
                "location": room["location"],
                "available": not conflicts,
                "conflicts": [
                    {
                        "booking_id": int(row["id"]),
                        "title": row["title"],
                        "start": row["start_ts"],
                        "end": row["end_ts"],
                        "booked_by": row["username"],
                    }
                    for row in conflicts
                ],
            }
        )
    return result


def suggest_rooms(
    conn: sqlite3.Connection,
    start_value: str | datetime,
    end_value: str | datetime,
    min_capacity: int = 0,
) -> list[dict]:
    availability = check_availability(conn, start_value, end_value, None, min_capacity)
    return sorted(
        [room for room in availability if room["available"]],
        key=lambda room: (room["capacity"], room["room_name"]),
    )


def get_room_info(conn: sqlite3.Connection, room_name: str) -> dict[str, object]:
    room = get_room_by_name(conn, room_name)
    if not room or not room["is_active"]:
        raise ValueError(f"Room not found or inactive: {room_name}")
    return {
        "room_id": int(room["id"]),
        "room_name": room["name"],
        "capacity": int(room["capacity"]),
        "location": room["location"],
        "color": room["color"],
        "is_active": bool(room["is_active"]),
    }


def _insert_booking(
    conn: sqlite3.Connection,
    room_id: int,
    user_id: int,
    title: str,
    start: datetime,
    end: datetime,
    recurrence_rule_id: int | None = None,
    series_id: str | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO bookings (room_id, user_id, title, start_ts, end_ts, recurrence_rule_id, series_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (room_id, user_id, title.strip(), dt_to_db(start), dt_to_db(end), recurrence_rule_id, series_id),
    )
    return int(cur.lastrowid)


def create_booking(
    conn: sqlite3.Connection,
    room_id: int,
    user_id: int,
    title: str,
    start_value: str | datetime,
    end_value: str | datetime,
    actor: dict,
    recurrence: dict | None = None,
) -> list[int]:
    start = parse_dt(start_value)
    end = parse_dt(end_value)
    occurrences = [(start, end)]
    recurrence_rule_id = None
    series_id = None
    if recurrence and recurrence.get("frequency"):
        occurrences = generate_occurrences(
            start,
            end,
            recurrence["frequency"],
            int(recurrence.get("interval_count") or 1),
            recurrence.get("until_date"),
            recurrence.get("occurrence_count"),
        )
        if len(occurrences) > 1:
            series_id = str(uuid.uuid4())

    for occurrence_start, occurrence_end in occurrences:
        validate_time_window(conn, occurrence_start, occurrence_end)
        conflicts = find_conflicts(conn, room_id, occurrence_start, occurrence_end)
        if conflicts:
            first = conflicts[0]
            raise ValueError(
                f"Room is already booked for {first['title']} from {first['start_ts']} to {first['end_ts']}."
            )

    if series_id:
        rule = recurrence or {}
        cur = conn.execute(
            """
            INSERT INTO recurrence_rules (frequency, interval_count, until_date, occurrence_count)
            VALUES (?, ?, ?, ?)
            """,
            (
                rule["frequency"],
                int(rule.get("interval_count") or 1),
                _date_or_none(rule.get("until_date")),
                rule.get("occurrence_count"),
            ),
        )
        recurrence_rule_id = int(cur.lastrowid)

    booking_ids = [
        _insert_booking(conn, room_id, user_id, title, occurrence_start, occurrence_end, recurrence_rule_id, series_id)
        for occurrence_start, occurrence_end in occurrences
    ]
    conn.commit()
    log_action(conn, actor["id"], "create_booking", "booking", booking_ids[0], f"count={len(booking_ids)}")
    return booking_ids


def update_booking(
    conn: sqlite3.Connection,
    booking_id: int,
    actor: dict,
    title: str | None = None,
    room_id: int | None = None,
    start_value: str | datetime | None = None,
    end_value: str | datetime | None = None,
    scope: str = "single",
) -> int:
    booking = get_booking(conn, booking_id)
    if not booking:
        raise ValueError("Booking not found.")
    can_manage_booking(actor, booking)
    target_ids = _scope_booking_ids(conn, booking, scope)
    original_start = db_to_dt(booking["start_ts"])
    original_end = db_to_dt(booking["end_ts"])
    duration = original_end - original_start
    new_room_id = room_id or int(booking["room_id"])
    exclude_ids = set(target_ids)

    updates: list[tuple[int, datetime, datetime]] = []
    for target_id in target_ids:
        row = get_booking(conn, target_id)
        row_start = db_to_dt(row["start_ts"])
        if start_value is not None and target_id == booking_id:
            new_start = parse_dt(start_value)
        elif start_value is not None and scope == "series":
            delta = parse_dt(start_value) - original_start
            new_start = row_start + delta
        else:
            new_start = row_start
        if end_value is not None and target_id == booking_id:
            new_end = parse_dt(end_value)
        elif end_value is not None and scope == "series":
            new_duration = parse_dt(end_value) - parse_dt(start_value) if start_value is not None else parse_dt(end_value) - original_start
            new_end = new_start + new_duration
        else:
            new_end = new_start + duration
        updates.append((target_id, new_start, new_end))

    for _, new_start, new_end in updates:
        validate_time_window(conn, new_start, new_end)
        conflicts = find_conflicts(conn, new_room_id, new_start, new_end, exclude_ids)
        if conflicts:
            first = conflicts[0]
            raise ValueError(f"Conflict with booking {first['id']}: {first['title']}.")

    for target_id, new_start, new_end in updates:
        conn.execute(
            """
            UPDATE bookings
            SET title = COALESCE(?, title),
                room_id = ?,
                start_ts = ?,
                end_ts = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (title.strip() if title else None, new_room_id, dt_to_db(new_start), dt_to_db(new_end), target_id),
        )
    conn.commit()
    log_action(conn, actor["id"], "update_booking", "booking", booking_id, f"scope={scope}")
    return len(target_ids)


def delete_booking(conn: sqlite3.Connection, booking_id: int, actor: dict, scope: str = "single") -> int:
    booking = get_booking(conn, booking_id)
    if not booking:
        raise ValueError("Booking not found.")
    can_manage_booking(actor, booking)
    target_ids = _scope_booking_ids(conn, booking, scope)
    conn.executemany(
        "UPDATE bookings SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        [(target_id,) for target_id in target_ids],
    )
    conn.commit()
    log_action(conn, actor["id"], "delete_booking", "booking", booking_id, f"scope={scope}")
    return len(target_ids)


def get_booking(conn: sqlite3.Connection, booking_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT b.*, r.name AS room_name, r.color AS room_color, u.username
        FROM bookings b
        JOIN rooms r ON r.id = b.room_id
        JOIN users u ON u.id = b.user_id
        WHERE b.id = ?
        """,
        (booking_id,),
    ).fetchone()


def can_manage_booking(actor: dict, booking: sqlite3.Row) -> None:
    if actor.get("is_admin") or int(booking["user_id"]) == int(actor["id"]):
        return
    raise PermissionError("You can only manage your own bookings.")


def _scope_booking_ids(conn: sqlite3.Connection, booking: sqlite3.Row, scope: str) -> list[int]:
    if scope == "series" and booking["series_id"]:
        rows = conn.execute(
            "SELECT id FROM bookings WHERE series_id = ? AND status = 'active' ORDER BY start_ts",
            (booking["series_id"],),
        ).fetchall()
        return [int(row["id"]) for row in rows]
    return [int(booking["id"])]


def list_bookings(
    conn: sqlite3.Connection,
    user_id: int | None = None,
    active_only: bool = True,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[sqlite3.Row]:
    clauses = []
    params: list[object] = []
    if active_only:
        clauses.append("b.status = 'active'")
    if user_id is not None:
        clauses.append("b.user_id = ?")
        params.append(user_id)
    if start_date:
        clauses.append("b.end_ts > ?")
        params.append(datetime.combine(start_date, time.min).isoformat(timespec="minutes"))
    if end_date:
        clauses.append("b.start_ts < ?")
        params.append(datetime.combine(end_date + timedelta(days=1), time.min).isoformat(timespec="minutes"))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return list(
        conn.execute(
            f"""
            SELECT b.*, r.name AS room_name, r.color AS room_color, u.username
            FROM bookings b
            JOIN rooms r ON r.id = b.room_id
            JOIN users u ON u.id = b.user_id
            {where}
            ORDER BY b.start_ts
            """,
            params,
        )
    )


def generate_occurrences(
    start: datetime,
    end: datetime,
    frequency: str,
    interval_count: int = 1,
    until_date: str | date | None = None,
    occurrence_count: int | None = None,
) -> list[tuple[datetime, datetime]]:
    if frequency not in {"daily", "weekly", "monthly"}:
        raise ValueError("Frequency must be daily, weekly, or monthly.")
    if interval_count < 1:
        raise ValueError("Recurrence interval must be at least 1.")
    if not until_date and not occurrence_count:
        occurrence_count = 10
    until = parse_date(until_date) if until_date else None
    max_count = min(int(occurrence_count or 500), 500)
    duration = end - start
    occurrences = []
    current = start
    while len(occurrences) < max_count:
        if until and current.date() > until:
            break
        occurrences.append((current, current + duration))
        current = _advance(current, frequency, interval_count)
    return occurrences


def _advance(value: datetime, frequency: str, interval_count: int) -> datetime:
    if frequency == "daily":
        return value + timedelta(days=interval_count)
    if frequency == "weekly":
        return value + timedelta(weeks=interval_count)
    month = value.month - 1 + interval_count
    year = value.year + month // 12
    month = month % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _date_or_none(value: object) -> str | None:
    if not value:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return str(value)
