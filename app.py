from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from classroom_booking import APP_NAME
from classroom_booking import agent
from classroom_booking import analytics
from classroom_booking import auth
from classroom_booking import booking_service as service
from classroom_booking.db import connect, default_db_path, init_db

try:
    from streamlit_calendar import calendar
except Exception:
    calendar = None


st.set_page_config(page_title=APP_NAME, page_icon=":school:", layout="wide")


@st.cache_resource
def get_conn():
    conn = connect(default_db_path())
    init_db(conn)
    return conn


def main() -> None:
    conn = get_conn()
    st.title(APP_NAME)
    st.caption("SQLite classroom booking with chat, calendar management, holidays, recurrence, and analytics.")

    if auth.user_count(conn) == 0:
        first_admin_form(conn)
        return

    user = st.session_state.get("user")
    if not user:
        login_form(conn)
        return

    with st.sidebar:
        st.markdown(f"Signed in as **{user['username']}**")
        st.caption("Admin" if user["is_admin"] else "User")
        if st.button("Sign out", use_container_width=True):
            st.session_state.clear()
            st.rerun()

    tabs = ["Chat", "Calendar", "My Bookings", "Availability Heatmap"]
    if user["is_admin"]:
        tabs.append("Admin")
    selected_tabs = st.tabs(tabs)
    render_chat(conn, user, selected_tabs[0])
    render_calendar(conn, user, selected_tabs[1])
    render_my_bookings(conn, user, selected_tabs[2])
    render_heatmap(conn, selected_tabs[3])
    if user["is_admin"]:
        render_admin(conn, user, selected_tabs[4])


def first_admin_form(conn) -> None:
    st.info("Create the first administrator account.")
    with st.form("first_admin"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Create admin")
    if submitted:
        try:
            user_id = auth.create_user(conn, username, password, is_admin=True)
            st.session_state.user = auth.get_user(conn, user_id)
            st.success("Admin created.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))


def login_form(conn) -> None:
    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")
    if submitted:
        user = auth.authenticate(conn, username, password)
        if user:
            st.session_state.user = user
            st.rerun()
        st.error("Invalid username or password.")


def render_chat(conn, user: dict, tab) -> None:
    with tab:
        st.subheader("Booking Assistant")
        api_key = agent.openai_api_key_from_streamlit(st)
        if not api_key:
            st.warning("OPENAI_API_KEY is not configured. The UI still works, but chat is disabled.")
            return
        if "chat_messages" not in st.session_state:
            st.session_state.chat_messages = [
                {"role": "assistant", "content": "Ask me to check availability, book a room, or manage your bookings."}
            ]
        render_sample_prompts()
        for message in st.session_state.chat_messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        prompt = st.chat_input("Example: Book Room A tomorrow 10:00 to 11:00 for Physics")
        if prompt:
            st.session_state.chat_messages.append({"role": "user", "content": prompt})
            if st.session_state.get("pending_tool") and prompt.strip().lower() in {"confirm", "yes", "proceed"}:
                pending = st.session_state.pop("pending_tool")
                try:
                    result = agent.execute_tool(conn, user, pending["name"], pending["arguments"])
                    reply = f"Confirmed. Result: `{result}`"
                except Exception as exc:
                    reply = f"I could not complete that action: {exc}"
            else:
                try:
                    result = agent.chat(conn, user, st.session_state.chat_messages, api_key)
                    reply = result.message
                    if result.pending_tool:
                        st.session_state.pending_tool = result.pending_tool
                except Exception as exc:
                    reply = f"Chat failed: {exc}"
            st.session_state.chat_messages.append({"role": "assistant", "content": reply})
            st.rerun()


def render_sample_prompts() -> None:
    examples = {
        "Check availability": [
            "Which classrooms are available on 15-Jul-2026 from 10:00 to 12:00?",
            "Is Room A free on 16-Jul-2026 from 14:00 to 15:30?",
        ],
        "Single booking": [
            "Book Room A on 15-Jul-2026 from 10:00 to 11:00 for Physics lecture.",
            "Reserve any available classroom on 17-Jul-2026 from 09:00 to 10:30 for project discussion.",
        ],
        "Recurring booking": [
            "Book Room B every Monday from 20-Jul-2026 to 14-Sep-2026, 11:00 to 12:00, for Chemistry lab.",
            "Create a weekly booking for Room C starting 22-Jul-2026 from 15:00 to 16:00 for 8 occurrences named Tutorial session.",
        ],
        "Modify booking": [
            "Change booking 12 to Room B on 21-Jul-2026 from 13:00 to 14:00.",
            "Update the title of booking 15 to Guest lecture.",
        ],
        "Delete booking": [
            "Delete booking 12.",
            "Cancel the whole recurring series for booking 18.",
        ],
    }
    with st.expander("Sample prompts", expanded=False):
        for heading, prompts in examples.items():
            st.markdown(f"**{heading}**")
            for prompt in prompts:
                st.code(prompt, language="text")


def render_calendar(conn, user: dict, tab) -> None:
    with tab:
        st.subheader("Booking Calendar")
        col1, col2, col3 = st.columns(3)
        today = date.today()
        with col1:
            start = st.date_input("From", today - timedelta(days=14), key="cal_from")
        with col2:
            end = st.date_input("To", today + timedelta(days=45), key="cal_to")
        with col3:
            view = st.selectbox(
                "View",
                [
                    "dayGridMonth",
                    "timeGridWeek",
                    "timeGridDay",
                    "listWeek",
                    "multiMonthYear",
                ],
            )
        closed_weekdays = service.get_closed_weekdays(conn)
        rows = service.list_bookings(conn, start_date=start, end_date=end)
        events = [
            {
                "id": str(row["id"]),
                "title": f"{row['room_name']}: {row['title']}",
                "start": row["start_ts"],
                "end": row["end_ts"],
                "backgroundColor": row["room_color"],
                "borderColor": row["room_color"],
            }
            for row in rows
        ]
        events.extend(calendar_holiday_events(conn, start, end))
        if calendar:
            options = {
                "initialView": view,
                "height": 720,
                "selectable": True,
                "editable": False,
                "nowIndicator": True,
                "hiddenDays": fullcalendar_hidden_days(closed_weekdays),
                "headerToolbar": {
                    "left": "prev,next today",
                    "center": "title",
                    "right": "dayGridMonth,timeGridWeek,timeGridDay,listWeek,multiMonthYear",
                },
            }
            calendar(events=events, options=options, key=f"calendar_{view}_{start}_{end}")
        else:
            st.warning("Install streamlit-calendar for interactive calendar views.")
            st.dataframe(pd.DataFrame(events), use_container_width=True)
        st.caption("Date-specific holidays are shown in red. Weekly closed days are hidden and cannot be booked.")

        st.divider()
        quick_booking_form(conn, user)


def fullcalendar_hidden_days(closed_weekdays: set[int]) -> list[int]:
    return sorted((weekday + 1) % 7 for weekday in closed_weekdays)


def calendar_holiday_events(conn, start: date, end: date) -> list[dict]:
    events = []
    closed_weekdays = service.get_closed_weekdays(conn)
    for holiday in service.list_holidays(conn):
        holiday_date = date.fromisoformat(holiday["holiday_date"])
        if holiday_date.weekday() in closed_weekdays:
            continue
        if start <= holiday_date <= end:
            events.append(
                {
                    "id": f"holiday-{holiday['id']}",
                    "title": f"Holiday: {holiday['name']}",
                    "start": holiday_date.isoformat(),
                    "end": (holiday_date + timedelta(days=1)).isoformat(),
                    "allDay": True,
                    "backgroundColor": "#dc2626",
                    "borderColor": "#991b1b",
                    "textColor": "#ffffff",
                    "editable": False,
                }
            )
    return events


def quick_booking_form(conn, user: dict) -> None:
    st.markdown("#### Quick Booking")
    rooms = service.list_rooms(conn)
    if not rooms:
        st.info("No active rooms exist yet. Ask an admin to create rooms.")
        return
    room_options = {room["name"]: int(room["id"]) for room in rooms}
    with st.form("quick_booking"):
        title = st.text_input("Title")
        room_name = st.selectbox("Room", list(room_options))
        col1, col2 = st.columns(2)
        with col1:
            booking_date = st.date_input("Date", date.today())
            start_time = st.time_input("Start time", time(9, 0))
        with col2:
            end_date = st.date_input("End date", booking_date)
            end_time = st.time_input("End time", time(10, 0))
        date_range_start = datetime.combine(booking_date, time.min)
        date_range_end = datetime.combine(end_date + timedelta(days=1), time.min)
        holiday_dates = service.holiday_dates_between(conn, date_range_start, date_range_end)
        closed_dates = service.closed_dates_between(conn, date_range_start, date_range_end)
        if holiday_dates:
            st.warning(f"Bookings are not allowed on holidays: {', '.join(sorted(holiday_dates))}.")
        if closed_dates:
            st.warning(f"Bookings are not allowed on closed days: {service.format_closed_dates(closed_dates)}.")
        recurring = st.checkbox("Recurring")
        recurrence = None
        if recurring:
            c1, c2, c3 = st.columns(3)
            frequency = c1.selectbox("Frequency", ["daily", "weekly", "monthly"])
            until = c2.date_input("Until", booking_date + timedelta(days=30))
            count = c3.number_input("Max occurrences", min_value=1, max_value=500, value=10)
            recurrence = {"frequency": frequency, "until_date": until, "occurrence_count": int(count)}
        submitted = st.form_submit_button("Create booking", disabled=bool(holiday_dates or closed_dates))
    if submitted:
        try:
            ids = service.create_booking(
                conn,
                room_options[room_name],
                user["id"],
                title,
                datetime.combine(booking_date, start_time),
                datetime.combine(end_date, end_time),
                user,
                recurrence,
            )
            st.success(f"Created {len(ids)} booking(s).")
        except Exception as exc:
            st.error(str(exc))


def render_my_bookings(conn, user: dict, tab) -> None:
    with tab:
        st.subheader("My Bookings" if not user["is_admin"] else "Bookings")
        rows = service.list_bookings(conn, user_id=None if user["is_admin"] else user["id"])
        if not rows:
            st.info("No active bookings.")
            return
        rooms = service.list_rooms(conn)
        room_options = {room["name"]: int(room["id"]) for room in rooms}
        for row in rows:
            label = f"#{row['id']} {row['title']} - {row['room_name']} - {row['start_ts']} to {row['end_ts']}"
            with st.expander(label):
                st.write(f"Booked by: {row['username']}")
                with st.form(f"edit_{row['id']}"):
                    title = st.text_input("Title", row["title"])
                    room_names = list(room_options)
                    current_index = room_names.index(row["room_name"]) if row["room_name"] in room_names else 0
                    room_name = st.selectbox("Room", room_names, index=current_index)
                    start_dt = service.db_to_dt(row["start_ts"])
                    end_dt = service.db_to_dt(row["end_ts"])
                    col1, col2 = st.columns(2)
                    with col1:
                        start_date = st.date_input("Start date", start_dt.date(), key=f"sd_{row['id']}")
                        start_time = st.time_input("Start time", start_dt.time(), key=f"st_{row['id']}")
                    with col2:
                        end_date = st.date_input("End date", end_dt.date(), key=f"ed_{row['id']}")
                        end_time = st.time_input("End time", end_dt.time(), key=f"et_{row['id']}")
                    scope = st.radio("Scope", ["single", "series"], horizontal=True, key=f"scope_{row['id']}")
                    c1, c2 = st.columns(2)
                    save = c1.form_submit_button("Save changes")
                    cancel = c2.form_submit_button("Delete booking")
                if save:
                    try:
                        count = service.update_booking(
                            conn,
                            int(row["id"]),
                            user,
                            title=title,
                            room_id=room_options[room_name],
                            start_value=datetime.combine(start_date, start_time),
                            end_value=datetime.combine(end_date, end_time),
                            scope=scope,
                        )
                        st.success(f"Updated {count} booking(s).")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
                delete_key = f"confirm_delete_booking_{row['id']}"
                if cancel:
                    st.session_state[delete_key] = scope
                    st.rerun()
                pending_delete_scope = st.session_state.get(delete_key)
                if pending_delete_scope:
                    st.warning(
                        f"Confirm delete booking #{row['id']} ({pending_delete_scope}). This cannot be undone."
                    )
                    confirm_col, cancel_col = st.columns(2)
                    if confirm_col.button("Confirm delete", key=f"do_delete_booking_{row['id']}"):
                        try:
                            count = service.delete_booking(conn, int(row["id"]), user, scope=pending_delete_scope)
                            st.session_state.pop(delete_key, None)
                            st.success(f"Deleted {count} booking(s).")
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))
                    if cancel_col.button("Cancel delete", key=f"cancel_delete_booking_{row['id']}"):
                        st.session_state.pop(delete_key, None)
                        st.rerun()


def render_heatmap(conn, tab) -> None:
    with tab:
        st.subheader("Room Availability Heatmap")
        c1, c2 = st.columns(2)
        start = c1.date_input("Analytics from", date.today().replace(day=1), key="heat_from")
        end = c2.date_input("Analytics to", date.today() + timedelta(days=30), key="heat_to")
        heatmap = analytics.heatmap_dataframe(conn, start, end)
        if heatmap.empty:
            st.info("No bookings in the selected range.")
        else:
            fig = px.imshow(
                heatmap,
                text_auto=True,
                aspect="auto",
                color_continuous_scale="Blues",
                labels={"color": "Booked hours"},
            )
            st.plotly_chart(fig, use_container_width=True)
        util = analytics.utilization_dataframe(conn, start, end)
        if not util.empty:
            st.markdown("#### Utilization")
            st.dataframe(util, use_container_width=True, hide_index=True)


def render_admin(conn, user: dict, tab) -> None:
    with tab:
        st.subheader("Admin")
        room_tab, user_tab, holiday_tab, audit_tab = st.tabs(["Rooms", "Users", "Holidays", "Audit"])
        with room_tab:
            admin_rooms(conn, user)
        with user_tab:
            admin_users(conn, user)
        with holiday_tab:
            admin_holidays(conn, user)
        with audit_tab:
            rows = conn.execute("SELECT * FROM audit_log ORDER BY created_at DESC LIMIT 200").fetchall()
            st.dataframe(pd.DataFrame([dict(row) for row in rows]), use_container_width=True, hide_index=True)


def admin_rooms(conn, user: dict) -> None:
    with st.form("add_room"):
        st.markdown("#### Add Room")
        name = st.text_input("Room name")
        capacity = st.number_input("Capacity", min_value=0, value=30)
        location = st.text_input("Location")
        color = st.color_picker("Room color", "#2563eb")
        submitted = st.form_submit_button("Add room")
    if submitted:
        try:
            service.create_room(conn, name, capacity, location, color, user)
            st.success("Room added.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    st.markdown("#### Room Color Legend")
    for room in service.list_rooms(conn, active_only=False):
        with st.expander(f"{room['name']} ({'active' if room['is_active'] else 'inactive'})"):
            with st.form(f"room_{room['id']}"):
                name = st.text_input("Name", room["name"])
                capacity = st.number_input("Capacity", min_value=0, value=int(room["capacity"]))
                location = st.text_input("Location", room["location"])
                color = st.color_picker("Color", room["color"])
                active = st.checkbox("Active", bool(room["is_active"]))
                save = st.form_submit_button("Save room")
            if save:
                try:
                    service.update_room(conn, int(room["id"]), name, capacity, location, color, active, user)
                    st.success("Room updated.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))


def admin_users(conn, user: dict) -> None:
    with st.form("add_user"):
        st.markdown("#### Add User")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        is_admin = st.checkbox("Admin")
        submitted = st.form_submit_button("Add user")
    if submitted:
        try:
            auth.create_user(conn, username, password, is_admin, actor_id=user["id"])
            st.success("User added.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    for row in auth.list_users(conn):
        with st.expander(f"{row['username']} ({'admin' if row['is_admin'] else 'user'})"):
            c1, c2 = st.columns(2)
            is_admin = c1.checkbox("Admin", bool(row["is_admin"]), key=f"admin_{row['id']}")
            is_active = c2.checkbox("Active", bool(row["is_active"]), key=f"active_{row['id']}")
            new_password = st.text_input("New password", type="password", key=f"pw_{row['id']}")
            if st.button("Save user", key=f"save_user_{row['id']}"):
                try:
                    auth.set_user_admin(conn, int(row["id"]), is_admin, user["id"])
                    auth.set_user_active(conn, int(row["id"]), is_active, user["id"])
                    if new_password:
                        auth.reset_password(conn, int(row["id"]), new_password, user["id"])
                    st.success("User updated.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))


def admin_holidays(conn, user: dict) -> None:
    weekday_names = service.WEEKDAY_NAMES
    current_closed = service.get_closed_weekdays(conn)
    with st.form("weekly_closed_days"):
        st.markdown("#### Weekly Closed Days")
        selected_days = st.multiselect(
            "Closed every week",
            weekday_names,
            default=[weekday_names[index] for index in sorted(current_closed)],
            help="These days are hidden from the calendar and cannot be booked.",
        )
        save_closed_days = st.form_submit_button("Save weekly closed days")
    if save_closed_days:
        try:
            selected_indices = [weekday_names.index(day_name) for day_name in selected_days]
            service.set_closed_weekdays(conn, selected_indices, user)
            st.success("Weekly closed days saved.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    st.markdown("#### Date-Specific Holidays")
    with st.form("holiday"):
        holiday_date = st.date_input("Holiday date", date.today())
        name = st.text_input("Holiday name")
        submitted = st.form_submit_button("Save holiday")
    if submitted:
        try:
            service.upsert_holiday(conn, holiday_date, name or "Holiday", user)
            st.success("Holiday saved.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    for row in service.list_holidays(conn):
        c1, c2, c3 = st.columns([2, 4, 1])
        c1.write(row["holiday_date"])
        c2.write(row["name"])
        delete_key = f"confirm_delete_holiday_{row['id']}"
        if c3.button("Delete", key=f"holiday_{row['id']}"):
            st.session_state[delete_key] = True
            st.rerun()
        if st.session_state.get(delete_key):
            st.warning(f"Confirm delete holiday {row['holiday_date']} - {row['name']}. This cannot be undone.")
            confirm_col, cancel_col = st.columns(2)
            if confirm_col.button("Confirm delete", key=f"do_delete_holiday_{row['id']}"):
                service.delete_holiday(conn, int(row["id"]), user)
                st.session_state.pop(delete_key, None)
                st.success("Holiday deleted.")
                st.rerun()
            if cancel_col.button("Cancel delete", key=f"cancel_delete_holiday_{row['id']}"):
                st.session_state.pop(delete_key, None)
                st.rerun()



if __name__ == "__main__":
    main()
