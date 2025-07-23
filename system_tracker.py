import streamlit as st
import pymysql
import pandas as pd
from datetime import datetime, timedelta

# Database configuration
DB_CONFIG = {
    'host': '15.235.85.189',
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
            # Create usage_log table with reason column
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS usage_log (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(255) NOT NULL,
                    email VARCHAR(255) NOT NULL,
                    system_ip VARCHAR(15) NOT NULL,
                    start_time DATETIME NOT NULL,
                    end_time DATETIME NULL,
                    duration_minutes INT NULL,
                    planned_duration INT NULL,
                    reason TEXT -- Add column for reason
                )
            """)
            # Create usage_queue table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS usage_queue (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(255) NOT NULL,
                    email VARCHAR(255) NOT NULL,
                    requested_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    reason TEXT,
                    INDEX idx_requested_time (requested_time)
                )
            """)
        connection.commit()
        return connection
    except Exception as e:
        st.error(f"Database connection failed: {e}")
        return None

# --- Existing Functions (potentially modified) ---
def get_active_sessions(connection):
    try:
        with connection.cursor() as cursor:
            # Add 'reason' to the SELECT list
            cursor.execute("""
                SELECT username, email, system_ip, start_time, planned_duration, reason
                FROM usage_log
                WHERE end_time IS NULL
            """)
            return cursor.fetchall()
    except Exception as e:
        st.error(f"Error fetching active sessions: {e}")
        return []

def start_session(connection, username, email, system_ip, planned_duration, reason): # Add 'reason' parameter
    try:
        with connection.cursor() as cursor:
            # Include 'reason' in the INSERT statement
            cursor.execute("""
                INSERT INTO usage_log (username, email, system_ip, start_time, planned_duration, reason)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (username, email, system_ip, datetime.now(), planned_duration, reason)) # Pass 'reason'
        connection.commit()
        return True
    except Exception as e:
        st.error(f"Error starting session: {e}")
        return False

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

def get_usage_history(connection):
    try:
        with connection.cursor() as cursor:
            # Add 'reason' to the SELECT list
            cursor.execute("""
                SELECT username, email, system_ip, start_time, end_time, duration_minutes, planned_duration, reason
                FROM usage_log
                ORDER BY start_time DESC
                LIMIT 50
            """)
            return cursor.fetchall()
    except Exception as e:
        st.error(f"Error fetching history: {e}")
        return []

# --- New Queue Management Functions ---
def add_to_queue(connection, username, email, reason):
    """Adds a user request to the queue."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO usage_queue (username, email, reason)
                VALUES (%s, %s, %s)
            """, (username, email, reason))
        connection.commit()
        return True
    except Exception as e:
        st.error(f"Error adding to queue: {e}")
        return False

def get_queue(connection):
    """Retrieves the current queue, ordered by request time."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT username, email, requested_time, reason
                FROM usage_queue
                ORDER BY requested_time ASC
            """)
            return cursor.fetchall()
    except Exception as e:
        st.error(f"Error fetching queue: {e}")
        return []

def remove_from_queue(connection, email):
    """Removes a user from the queue."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                DELETE FROM usage_queue
                WHERE email = %s
            """, (email,))
        connection.commit()
        return True
    except Exception as e:
        st.error(f"Error removing from queue: {e}")
        return False

def get_user_queue_position(connection, email):
    """Gets the position of a user in the queue (1-based index). Returns -1 if not in queue."""
    try:
        with connection.cursor() as cursor:
             # Get the user's request time
             cursor.execute("SELECT requested_time FROM usage_queue WHERE email = %s", (email,))
             user_time_result = cursor.fetchone()
             if not user_time_result:
                 return -1 # Not in queue
             user_request_time = user_time_result[0]

             # Count how many entries are older than the user's request time
             cursor.execute("SELECT COUNT(*) FROM usage_queue WHERE requested_time < %s", (user_request_time,))
             position_result = cursor.fetchone()
             if position_result:
                 return position_result[0] + 1 # Add 1 for 1-based indexing
             else:
                 return -1 # Shouldn't happen if user is in queue
    except Exception as e:
         st.error(f"Error getting queue position: {e}")
         return -1

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
        'planned_duration': session[4],
        'reason': session[5] # Add reason to system_users dict
    } for session in active_sessions}

    # --- Queue Management ---
    st.subheader("Queue Status")
    # Check if user is already in the queue
    user_queue_position = get_user_queue_position(connection, user_email)

    # Show user's queue position
    if user_queue_position > 0:
        st.info(f"You are currently #{user_queue_position} in the queue.")
    elif user_queue_position == 0: # Edge case if they are first
        st.info(f"You are currently #1 in the queue.")

    # Show the queue list
    queue_list = get_queue(connection)
    if queue_list:
        queue_df = pd.DataFrame(queue_list, columns=["User", "Email", "Requested Time", "Reason"])
        st.dataframe(queue_df[["User", "Requested Time", "Reason"]])
    else:
        st.write("No one is currently in the queue.")

    st.markdown("---")
    # --- End Queue Management ---

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

    # Determine selected system
    selected_system = None
    if available_systems:
        # If user is in queue, don't let them select a system directly
        if user_queue_position == -1: # Not in queue
            selected_system = st.selectbox("Available Systems", available_systems)
        else:
             st.info("You are in the queue. Please wait for a system to become available.")
             # Don't show selectbox, selected_system remains None
    else:
        st.warning("No systems are currently available")
        # Offer to join queue if not already in it
        if user_queue_position == -1:
            st.subheader("Join Queue")
            with st.form("queue_form_all_busy"):
                 queue_reason_all = st.text_area("Enter reason for needing a system:", key="queue_reason_all", placeholder="Please specify why you need access...")
                 submitted_to_queue_all = st.form_submit_button("Join Queue")
                 if submitted_to_queue_all:
                     if queue_reason_all.strip():
                         if add_to_queue(connection, username, user_email, queue_reason_all.strip()):
                             st.success("Added to the queue!")
                             st.rerun()
                         else:
                             st.error("Failed to join the queue.")
                     else:
                          st.error("Please enter a reason.")
        # selected_system remains None

    # Show unavailable systems with timers
    if unavailable_systems:
        st.subheader("Unavailable Systems")
        for system, user_info in unavailable_systems:
            start_time = user_info['start_time']
            planned_duration = user_info['planned_duration']
            reason = user_info.get('reason', '') # Get reason for display
            reason_display = f" (Reason: {reason})" if reason else ""
            if start_time and planned_duration:
                time_remaining = get_time_remaining(start_time, planned_duration)
                overdue = is_session_overdue(start_time, planned_duration)
                if overdue:
                    st.warning(f"🖥️ {system} is being used by **{user_info['username']}** (⏰ Time exceeded){reason_display}")
                elif time_remaining is not None:
                    st.info(f"🖥️ {system} is being used by **{user_info['username']}** (⏰ {time_remaining} min left){reason_display}")
                else:
                    st.info(f"🖥️ {system} is being used by **{user_info['username']}**{reason_display}")
            else:
                st.info(f"🖥️ {system} is being used by **{user_info['username']}**{reason_display}")

    # Stop processing if no system selected or user is in queue
    if not selected_system or user_queue_position > -1:
        # Proceed to show current status and history even if no system selected or user is queued
        pass
    else:
        # Check current status for selected system (existing logic)
        user_active = selected_system in system_users and system_users[selected_system]['email'] == user_email
        system_in_use_by_user = user_active
        system_in_use_by_other = selected_system in system_users and system_users[selected_system]['username'] != username

        # Show timer for user's active session (existing logic)
        if user_active:
            user_session = system_users[selected_system]
            start_time = user_session['start_time']
            planned_duration = user_session['planned_duration']
            reason = user_session.get('reason', '') # Get reason for display
            reason_display = f" (Reason: {reason})" if reason else ""
            if start_time and planned_duration:
                time_remaining = get_time_remaining(start_time, planned_duration)
                overdue = is_session_overdue(start_time, planned_duration)
                if overdue:
                    st.warning(f"⚠️ Time exceeded for {selected_system}! Please end session or extend usage.{reason_display}")
                elif time_remaining is not None:
                    st.success(f"✅ You are using {selected_system} ({time_remaining} minutes remaining){reason_display}")
                else:
                    st.success(f"✅ You are using {selected_system}{reason_display}")
            else:
                st.success(f"✅ You are using {selected_system}{reason_display}")

        # Toggle button (existing logic)
        st.subheader("Usage Status")
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
            # Check if user was in queue and wants to claim this now-free system
            was_in_queue = user_queue_position > -1
            if was_in_queue:
                st.info("You were in the queue. Claim this system now?")
                # Allow updating reason even if claiming from queue
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

                st.subheader("Reason for Usage")
                # Pre-fill reason from queue or allow editing
                queue_reason_for_claim = ""
                # Simple way to get the reason from the queue for pre-filling (requires another DB call or passing it)
                # Let's fetch it quickly for pre-fill
                try:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT reason FROM usage_queue WHERE email = %s", (user_email,))
                        queue_reason_result = cursor.fetchone()
                        if queue_reason_result:
                            queue_reason_for_claim = queue_reason_result[0]
                except:
                    pass # Ignore if can't fetch
                usage_reason = st.text_area("Briefly explain why you need this system:", value=queue_reason_for_claim, key="usage_reason_claim")

                if st.button("Claim System and Start Session"):
                    # 1. Remove user from queue
                    remove_from_queue(connection, user_email)
                    # 2. Start the session
                    if usage_reason.strip(): # Require reason
                        if start_session(connection, username, user_email, selected_system, planned_duration, usage_reason.strip()): # Pass reason
                            st.success(f"Claimed {selected_system} and started session ({selected_duration_label}). Removed from queue.")
                            st.rerun()
                        else:
                            # Re-add to queue? Or notify user of failure? For now, just error.
                            st.error("Failed to start session. You might need to re-join the queue.")
                    else:
                        st.error("Please enter a reason for using the system.")
            else:
                # Standard start session flow (user wasn't in queue)
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

                st.subheader("Reason for Usage")
                usage_reason = st.text_area("Briefly explain why you need this system:", key="usage_reason_new", placeholder="Please specify why you need access...")

                if st.button("Start Session"):
                    if usage_reason.strip(): # Require reason
                        if start_session(connection, username, user_email, selected_system, planned_duration, usage_reason.strip()): # Pass reason
                            st.success(f"Started session for {selected_system} ({selected_duration_label})")
                            st.rerun()
                        else:
                            st.error("Failed to start session")
                    else:
                        st.error("Please enter a reason for using the system.")

        elif status == "Inactive" and user_active:
            if st.button("End Session"):
                if end_session(connection, user_email, selected_system):
                    st.success(f"Ended session for {selected_system}")
                    # Optional: Notify next user in queue? (Requires more complex logic/websockets)
                    st.rerun()
                else:
                    st.error("Failed to end session")

    # --- Display current status and history (existing logic, potentially modified for reason) ---
    st.subheader("Current System Status")
    if active_sessions:
        enhanced_sessions = []
        now = datetime.now()
        for session in active_sessions:
            # session now includes 'reason' at index 5
            start_time = session[3]
            planned_duration = session[4]
            reason = session[5] # Get reason
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
            enhanced_session = list(session) # [username, email, ip, start_time, planned_duration, reason]
            enhanced_session.append(active_since) # index 6
            enhanced_session.append(status_text)   # index 7
            if time_remaining is not None:
                 enhanced_session.append(f"{time_remaining} min") # index 8
            else:
                 enhanced_session.append("N/A")                   # index 8
            # Optionally add reason to display in table
            # enhanced_session.append(reason) # index 9
            enhanced_sessions.append(enhanced_session)

        status_df = pd.DataFrame(enhanced_sessions, columns=[
            "User", "Email", "System IP", "Start Time", "Planned Duration", "Reason", "Active Since", "Status", "Time Remaining" # Add Reason if displayed
        ])
        # Display DataFrame, optionally including the Reason column
        st.dataframe(status_df[["User", "System IP", "Active Since", "Status", "Planned Duration", "Time Remaining"]]) # Add "Reason" column here if desired
    else:
        st.info("No active sessions")

    st.subheader("Recent Usage History")
    history = get_usage_history(connection)
    if history:
        history_df = pd.DataFrame(history, columns=[
            "User", "Email", "System IP", "Start Time", "End Time", "Actual Duration (min)", "Planned Duration (min)", "Reason" # Add Reason
        ])
        # Optionally display Reason column in dataframe
        st.dataframe(history_df[["User", "System IP", "Start Time", "End Time", "Actual Duration (min)", "Planned Duration (min)", "Reason"]]) # Include Reason
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
    # Initialize database (ensures tables are created)
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
