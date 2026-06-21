from __future__ import annotations

import sqlite3
from datetime import date

import pandas as pd

from .booking_service import db_to_dt, list_bookings


def bookings_dataframe(
    conn: sqlite3.Connection,
    start_date: date | None = None,
    end_date: date | None = None,
) -> pd.DataFrame:
    rows = list_bookings(conn, start_date=start_date, end_date=end_date)
    data = []
    for row in rows:
        start = db_to_dt(row["start_ts"])
        end = db_to_dt(row["end_ts"])
        data.append(
            {
                "booking_id": int(row["id"]),
                "room": row["room_name"],
                "user": row["username"],
                "title": row["title"],
                "date": start.date().isoformat(),
                "weekday": start.strftime("%a"),
                "hour": start.hour,
                "duration_hours": max((end - start).total_seconds() / 3600, 0),
            }
        )
    return pd.DataFrame(data)


def heatmap_dataframe(conn: sqlite3.Connection, start_date: date | None = None, end_date: date | None = None) -> pd.DataFrame:
    df = bookings_dataframe(conn, start_date, end_date)
    if df.empty:
        return pd.DataFrame()
    return df.pivot_table(
        index="room",
        columns="weekday",
        values="duration_hours",
        aggfunc="sum",
        fill_value=0,
    ).reindex(columns=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], fill_value=0)


def utilization_dataframe(conn: sqlite3.Connection, start_date: date, end_date: date) -> pd.DataFrame:
    df = bookings_dataframe(conn, start_date, end_date)
    rooms = pd.read_sql_query("SELECT name AS room FROM rooms WHERE is_active = 1 ORDER BY name", conn)
    if rooms.empty:
        return pd.DataFrame(columns=["room", "booked_hours", "utilization_percent"])
    days = max((end_date - start_date).days + 1, 1)
    available_hours = days * 10
    if df.empty:
        rooms["booked_hours"] = 0.0
    else:
        booked = df.groupby("room", as_index=False)["duration_hours"].sum().rename(columns={"duration_hours": "booked_hours"})
        rooms = rooms.merge(booked, on="room", how="left").fillna({"booked_hours": 0.0})
    rooms["utilization_percent"] = (rooms["booked_hours"] / available_hours * 100).round(1)
    return rooms.sort_values("utilization_percent", ascending=False)
