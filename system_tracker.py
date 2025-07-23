import streamlit as st
import pymysql
import pandas as pd
from datetime import datetime, timedelta

# Database configuration
DB_CONFIG = {
    'host': '172.27.131.163',
    'user': 'root',
    'password': 'actowiz',
    'database': 'system_usage',
    'charset': 'utf8mb4'
}


# Initialize database connection
def init_db():
    try:
        connection = pymysql.connect(**DB_CONFIG)
        with connection.cursor() as cursor:
            # Create tables if they don't exist
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS usage_log (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(255) NOT NULL,
                    email VARCHAR(255) NOT NULL,
                    system_ip VARCHAR(15) NOT NULL,
                    start_time DATETIME NOT NULL,
                    end_time DATETIME NULL,
                    duration_minutes INT NULL,
                    planned_duration INT NULL
                )
            """)
        connection.commit()
        return connection
    except Exception as e:
        st.error(f"Database connection failed: {e}")
        return None


# Get active sessions
def get_active_sessions(connection):
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT username, email, system_ip, start_time, planned_duration
                FROM usage_log 
                WHERE end_time IS NULL
            """)
            return cursor.fetchall()
    except Exception as e:
        st.error(f"Error fetching active sessions: {e}")
        return []


# Start new session
def start_session(connection, username, email, system_ip, planned_duration):
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO usage_log (username, email, system_ip, start_time, planned_duration) 
                VALUES (%s, %s, %s, %s, %s)
            """, (username, email, system_ip, datetime.now(), planned_duration))
        connection.commit()
        return True
    except Exception as e:
        st.error(f"Error starting session: {e}")
        return False


# End session
def end_session(connection, email, system_ip):
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE usage_log 
                SET end_time = %s, duration_minutes = TIMESTAMPDIFF(MINUTE, start_time, %s)
                WHERE email = %s AND system_ip = %s AND end_time IS NULL
            """, (datetime.now(), datetime.now(), email, system_ip))
        connection.commit()
        return True
    except Exception as e:
        st.error(f"Error ending session: {e}")
        return False


# Get usage history
def get_usage_history(connection):
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT username, email, system_ip, start_time, end_time, duration_minutes, planned_duration
                FROM usage_log
                ORDER BY start_time DESC
                LIMIT 50
            """)
            return cursor.fetchall()
    except Exception as e:
        st.error(f"Error fetching history: {e}")
        return []


# Calculate time remaining
def get_time_remaining(start_time, planned_duration):
    if not start_time or not planned_duration:
        return None
    end_time = start_time + timedelta(minutes=planned_duration)
    remaining = end_time - datetime.now()
    return max(0, int(remaining.total_seconds() / 60))


# Check if session is overdue
def is_session_overdue(start_time, planned_duration):
    if not start_time or not planned_duration:
        return False
    end_time = start_time + timedelta(minutes=planned_duration)
    return datetime.now() > end_time


# Format timedelta to human readable
def format_duration(td):
    if td is None:
        return "0m 0s"

    # Handle negative timedeltas
    if td.total_seconds() < 0:
        return "0m 0s"

    total_seconds = int(td.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m {seconds}s"


# Main app
def main_app():
    # Initialize database
    connection = init_db()
    if not connection:
        st.stop()

    # System options
    SYSTEMS = [
        "172.27.131.163",
        "172.27.131.164",
        "172.27.131.165"
    ]

    # Get user info from authentication
    user_info = st.session_state.get('user_info', {})
    username = user_info.get('name', 'Unknown User')
    user_email = user_info.get('email', '')

    # Header with user info
    st.title(f"Welcome, {username}!")

    st.markdown("---")

    # Get active sessions
    active_sessions = get_active_sessions(connection)

    # Create a dictionary of systems and their current users
    system_users = {session[2]: {
        'username': session[0],
        'email': session[1],
        'start_time': session[3],
        'planned_duration': session[4]
    } for session in active_sessions}

    # System selection with availability check
    st.subheader("Select System to Use")

    # Filter out systems that are already in use by other users
    available_systems = []
    unavailable_systems = []

    for system in SYSTEMS:
        if system in system_users:
            if system_users[system]['username'] == username:
                # User is already using this system
                available_systems.append(system)
            else:
                # Another user is using this system
                unavailable_systems.append((system, system_users[system]))
        else:
            # System is available
            available_systems.append(system)

    # Show available systems
    if available_systems:
        selected_system = st.selectbox("Available Systems", available_systems)
    else:
        st.warning("No systems are currently available")
        selected_system = None

    # Show unavailable systems with timers
    if unavailable_systems:
        st.subheader("Unavailable Systems")
        for system, user_info in unavailable_systems:
            start_time = user_info['start_time']
            planned_duration = user_info['planned_duration']

            if start_time and planned_duration:
                time_remaining = get_time_remaining(start_time, planned_duration)
                overdue = is_session_overdue(start_time, planned_duration)

                if overdue:
                    st.warning(f"🖥️ {system} is being used by **{user_info['username']}** (⏰ Time exceeded)")
                elif time_remaining is not None:
                    st.info(f"🖥️ {system} is being used by **{user_info['username']}** (⏰ {time_remaining} min left)")
                else:
                    st.info(f"🖥️ {system} is being used by **{user_info['username']}**")
            else:
                st.info(f"🖥️ {system} is being used by **{user_info['username']}**")

    if not selected_system:
        st.stop()

    # Check current status for selected system
    user_active = selected_system in system_users and system_users[selected_system]['email'] == user_email
    system_in_use_by_user = user_active
    system_in_use_by_other = selected_system in system_users and system_users[selected_system]['username'] != username

    # Show timer for user's active session
    if user_active:
        user_session = system_users[selected_system]
        start_time = user_session['start_time']
        planned_duration = user_session['planned_duration']

        if start_time and planned_duration:
            time_remaining = get_time_remaining(start_time, planned_duration)
            overdue = is_session_overdue(start_time, planned_duration)

            if overdue:
                st.warning(f"⚠️ Time exceeded for {selected_system}! Please end session or extend usage.")
            elif time_remaining is not None:
                st.success(f"✅ You are using {selected_system} ({time_remaining} minutes remaining)")
            else:
                st.success(f"✅ You are using {selected_system}")
        else:
            st.success(f"✅ You are using {selected_system}")

    # Toggle button
    st.subheader("Usage Status")

    # Disable toggle if system is used by another user
    if system_in_use_by_other:
        st.warning(f"This system is currently being used by {system_users[selected_system]['username']}")
        status = "Inactive"
    else:
        status = st.radio(
            f"Mark {selected_system} as:",
            ["Inactive", "Active"],
            index=1 if user_active else 0,
            key="status_toggle",
            horizontal=True
        )

    # Handle status change
    if status == "Active" and not user_active and not system_in_use_by_other:
        # Show duration selection when activating
        st.subheader("Planned Usage Duration")
        duration_options = {
            "15 minutes": 15,
            "30 minutes": 30,
            "45 minutes": 45,
            "1 hour": 60
        }
        selected_duration_label = st.selectbox(
            "Select planned duration:",
            list(duration_options.keys()),
            index=3  # Default to 1 hour (last option)
        )
        planned_duration = duration_options[selected_duration_label]

        if st.button("Start Session"):
            if start_session(connection, username, user_email, selected_system, planned_duration):
                st.success(f"Started session for {selected_system} ({selected_duration_label})")
                st.rerun()
            else:
                st.error("Failed to start session")
    elif status == "Inactive" and user_active:
        if st.button("End Session"):
            if end_session(connection, user_email, selected_system):
                st.success(f"Ended session for {selected_system}")
                st.rerun()
            else:
                st.error("Failed to end session")

    # Display current status
    st.subheader("Current System Status")
    if active_sessions:
        # Add time remaining and active since to active sessions
        enhanced_sessions = []
        now = datetime.now()
        for session in active_sessions:
            start_time = session[3]
            planned_duration = session[4]
            time_remaining = None
            active_since = "0m 0s"
            status_text = "Active"

            if start_time:
                try:
                    active_since_td = now - start_time
                    active_since = format_duration(active_since_td)
                except:
                    active_since = "0m 0s"

            if start_time and planned_duration:
                time_remaining = get_time_remaining(start_time, planned_duration)
                overdue = is_session_overdue(start_time, planned_duration)
                if overdue:
                    status_text = "⏰ Overdue"

            enhanced_session = list(session)
            enhanced_session.append(active_since)
            enhanced_session.append(status_text)

            if time_remaining is not None:
                enhanced_session.append(f"{time_remaining} min")
            else:
                enhanced_session.append("N/A")
            enhanced_sessions.append(enhanced_session)

        status_df = pd.DataFrame(enhanced_sessions, columns=[
            "User", "Email", "System IP", "Start Time", "Planned Duration", "Active Since", "Status", "Time Remaining"
        ])
        st.dataframe(status_df[["User", "System IP", "Active Since", "Status", "Planned Duration", "Time Remaining"]])
    else:
        st.info("No active sessions")

    # Display usage history
    st.subheader("Recent Usage History")
    history = get_usage_history(connection)
    if history:
        history_df = pd.DataFrame(history, columns=[
            "User", "Email", "System IP", "Start Time", "End Time", "Actual Duration (min)", "Planned Duration (min)"
        ])
        st.dataframe(history_df)
    else:
        st.info("No usage history found")


# Login screen
def login_screen():
    st.header("🔒 System Usage Tracker")
    st.subheader("Please log in with Google to continue")

    if st.button("Log in with Google", type="primary"):
        st.login(provider="google")


# Main application logic
def run_app():
    # Initialize database
    init_db()

    # Check if user is authenticated
    if (hasattr(st, 'user') and
            hasattr(st.user, 'email') and
            st.user.email):
        # User is authenticated, store info in session
        st.session_state.user_info = {
            'name': st.user.name,
            'email': st.user.email
        }
        main_app()
    elif st.session_state.get('user_info'):
        # User info already in session
        main_app()
    else:
        # Show login screen
        login_screen()


# Initialize session state keys if they don't exist
if 'user_info' not in st.session_state:
    st.session_state.user_info = None

# Run the app
if __name__ == "__main__":
    run_app()