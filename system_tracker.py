import streamlit as st
import pymysql
import pandas as pd
from datetime import datetime, timedelta
import requests
import pytz

# Database configuration
DB_CONFIG = {
    'host': '15.235.85.189',
    'user': 'root',
    'password': 'actowiz',
    'database': 'system_usage',
    'charset': 'utf8mb4'
}

# Slack Notification Configuration
SLACK_WEBHOOK_URL = 'http://51.222.244.92:8904/send_message' # Your webhook URL
HEADERS = {'Content-Type': 'application/json'}

# --- Change 2: Define IST timezone ---
IST_TZ = pytz.timezone('Asia/Kolkata')

# Initialize database connection
def init_db():
    try:
        connection = pymysql.connect(**DB_CONFIG)
        with connection.cursor() as cursor:
            # --- Change 3: Set MySQL session timezone to IST ---
            cursor.execute("SET time_zone = '+05:30'")
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
                    requested_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, -- This will now be in IST due to session TZ
                    reason TEXT,
                    INDEX idx_requested_time (requested_time)
                )
            """)
        connection.commit()
        return connection
    except Exception as e:
        st.error(f"Database connection failed: {e}")
        return None


def send_slack_notification(message,mention_type):
    """
    Sends a message to the configured Slack channel.
    """
    if not SLACK_WEBHOOK_URL:
        st.warning("Slack webhook URL not configured. Skipping notification.")
        return

    try:
        json_data = {
            'message': message,
            'mention_type': mention_type,  # Or 'here', 'everyone', or specific user IDs
        }
        response = requests.post(SLACK_WEBHOOK_URL, headers=HEADERS, json=json_data)

        # Check if the request was successful (optional, depends on your webhook's response)
        if response.status_code != 200:
            st.warning(
                f"Slack notification might have failed. Status code: {response.status_code}, Response: {response.text}")
        # If your webhook returns JSON indicating success/failure, you can check response.json() here
        # else:
        #     st.success("Slack notification sent successfully.") # Optional confirmation

    except Exception as e:
        st.error(f"Failed to send Slack notification: {e}")


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

# --- Change 4: Use IST datetime for start_time ---
def start_session(connection, username, email, system_ip, planned_duration, reason):
    try:
        # Get current time in IST
        ist_now = datetime.now(IST_TZ)
        with connection.cursor() as cursor:
            # Include 'reason' in the INSERT statement, use ist_now
            cursor.execute("""
                INSERT INTO usage_log (username, email, system_ip, start_time, planned_duration, reason)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (username, email, system_ip, ist_now, planned_duration, reason))
        connection.commit()

        message = f"🟢 *System Connected* | User: `{username}` | IP: `{system_ip}` | Duration: `{planned_duration} min` | Reason: `{reason}`"
        send_slack_notification(message,"channel")
        return True
    except Exception as e:
        st.error(f"Error starting session: {e}")
        return False

# --- Change 5: Use IST datetime for end_time ---
def end_session(connection, email, system_ip):
    try:
        # Get current time in IST
        ist_now = datetime.now(IST_TZ)
        with connection.cursor() as cursor:
            # Use ist_now for end_time calculation and update
            cursor.execute("""
                UPDATE usage_log
                SET end_time = %s, duration_minutes = TIMESTAMPDIFF(MINUTE, start_time, %s)
                WHERE email = %s AND system_ip = %s AND end_time IS NULL
            """, (ist_now, ist_now, email, system_ip))
        connection.commit()
        # --- Add Slack Notification Logic ---
        if cursor.rowcount > 0:  # Check if an update actually happened
            # 1. Notify that the system is now free
            # You might want to fetch the username for a more detailed message
            # For now, we know the email and IP
            message_free = f"🔵 *System Disconnected* | IP: `{system_ip}` is now *free*."
            send_slack_notification(message_free,"channel")

            # 2. Check if someone is in the queue and notify them
            next_user_info = get_next_user_in_queue(connection)
            if next_user_info:
                next_username, next_email = next_user_info
                # Format message to tag the user (assuming email maps to Slack user ID or they have notifications set up for mentions)
                # If your webhook supports tagging by email/user_id, use that. Otherwise, just mention the name/email.
                # Example using plain text mention (Slack often highlights names/emails):
                message_notify = f"<@{next_email}> or <{next_username}>, the system `{system_ip}` is now free! You are next in the queue."
                # If your webhook requires a specific format for user mentions, adjust the message accordingly.
                send_slack_notification(message_notify,"channel")
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

# The DEFAULT CURRENT_TIMESTAMP in the table definition will now use IST because of the session timezone.
# If you explicitly wanted to pass it (though not necessary with DEFAULT), you would use ist_now = datetime.now(IST_TZ)

def add_to_queue(connection, username, email, reason):
    """Adds a user request to the queue."""
    try:
        # Note: requested_time uses DEFAULT CURRENT_TIMESTAMP which is now IST due to session TZ
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO usage_queue (username, email, reason) -- requested_time defaults to CURRENT_TIMESTAMP (IST)
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


def get_next_user_in_queue(connection):
    """
    Retrieves the username and email of the user at the front of the queue.
    Returns a tuple (username, email) or None if queue is empty.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT username, email
                FROM usage_queue
                ORDER BY requested_time ASC
                LIMIT 1
            """)
            result = cursor.fetchone()
            return result # Returns (username, email) tuple or None
    except Exception as e:
        st.error(f"Error fetching next user from queue: {e}")
        return None

# Calculate time remaining - Ensure times used are timezone-aware if comparing with Python datetime
# --- Change 7: Ensure datetime.now() uses IST for comparisons ---
def get_time_remaining(start_time, planned_duration):
    if not start_time or not planned_duration:
        return None
    # Ensure start_time is treated as IST if it's naive (assumed to be IST from DB)
    if start_time.tzinfo is None:
        start_time = IST_TZ.localize(start_time)
    end_time = start_time + timedelta(minutes=planned_duration)
    # Get current time in IST for comparison
    now_ist = datetime.now(IST_TZ)
    remaining = end_time - now_ist
    return max(0, int(remaining.total_seconds() / 60))

# Check if session is overdue - Ensure times used are timezone-aware
# --- Change 8: Ensure datetime.now() uses IST for comparisons ---
def is_session_overdue(start_time, planned_duration):
    if not start_time or not planned_duration:
        return False
    # Ensure start_time is treated as IST if it's naive (assumed to be IST from DB)
    if start_time.tzinfo is None:
        start_time = IST_TZ.localize(start_time)
    end_time = start_time + timedelta(minutes=planned_duration)
    # Get current time in IST for comparison
    now_ist = datetime.now(IST_TZ)
    return now_ist > end_time


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
        # --- Change 1: Add option to leave the queue ---
        if st.button("Leave Queue"):
            if remove_from_queue(connection, user_email):
                st.success("Removed from the queue.")
                st.rerun()
            else:
                st.error("Failed to remove you from the queue.")
        # --- End Change 1 ---
    elif user_queue_position == 0: # Edge case if they are first
        st.info(f"You are currently #1 in the queue.")
        # --- Change 1: Add option to leave the queue (even if first) ---
        if st.button("Leave Queue"):
            if remove_from_queue(connection, user_email):
                st.success("Removed from the queue.")
                st.rerun()
            else:
                st.error("Failed to remove you from the queue.")
        # --- End Change 1 ---
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
            # System is available (free for anyone to claim)
            available_systems.append(system)
    # Determine selected system - Allow selection from available systems regardless of queue status
    selected_system = None
    if available_systems:
        # Show queue position reminder if user is in queue
        if user_queue_position > 0:
             st.info(f"You are currently #{user_queue_position} in the queue, but you can still claim an available system below.")
        elif user_queue_position == 0: # Handle edge case for position 1
             st.info(f"You are currently #1 in the queue, but you can still claim an available system below.")
        # Allow user to select any available system
        selected_system = st.selectbox("Available Systems", available_systems)
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
                             st.rerun() # Refresh to show updated queue position
                         else:
                             st.error("Failed to join the queue.")
                     else:
                          st.error("Please enter a reason.")
        # selected_system remains None
    # Show unavailable systems with timers (unchanged)
    if unavailable_systems:
        st.subheader("Unavailable Systems")
        for system, user_info in unavailable_systems:
            start_time = user_info['start_time']
            planned_duration = user_info['planned_duration']
            reason = user_info.get('reason', '') # Get reason for display
            reason_display = f" (Reason: {reason})" if reason else ""
            # if start_time and planned_duration:
            #     time_remaining = get_time_remaining(start_time, planned_duration)
            #     overdue = is_session_overdue(start_time, planned_duration)
            #     if overdue:
            #         st.warning(f"🖥️ {system} is being used by **{user_info['username']}** (⏰ Time exceeded){reason_display}")
            #     elif time_remaining is not None:
            #         st.info(f"🖥️ {system} is being used by **{user_info['username']}** (⏰ {time_remaining} min left){reason_display}")
            #     else:
            #         st.info(f"🖥️ {system} is being used by **{user_info['username']}**{reason_display}")
            # else:
            #     st.info(f"🖥️ {system} is being used by **{user_info['username']}**{reason_display}")
            if start_time and planned_duration:
                time_remaining = get_time_remaining(start_time, planned_duration)
                overdue = is_session_overdue(start_time, planned_duration)
                if overdue:
                    st.warning(
                        f"🖥️ {system} is being used by **{user_info['username']}** (⏰ Time exceeded){reason_display}")
                    # --- Add Slack Notification for Overdue (Other Users) ---
                    # Create a unique key for this specific system/user overdue event
                    overdue_key = f"{system}_{user_info['email']}"
                    if overdue_key not in st.session_state.overdue_notifications_sent:
                        # Format the message
                        message = f"⚠️ *Session Overdue* | User: `{user_info['username']}` (`{user_info['email']}`) | IP: `{system}` | Reason: `{reason}`"
                        send_slack_notification(message,"channel")
                        # Mark this notification as sent to avoid repeated messages
                        st.session_state.overdue_notifications_sent.add(overdue_key)
                    # --- End Slack Notification ---
                elif time_remaining is not None:
                    st.info(
                        f"🖥️ {system} is being used by **{user_info['username']}** (⏰ {time_remaining} min left){reason_display}")
                    # --- Optional: Clear notification flag if session is no longer overdue ---
                    # This handles the case where time is extended or session ends, then becomes overdue again.
                    overdue_key = f"{system}_{user_info['email']}"
                    if overdue_key in st.session_state.overdue_notifications_sent:
                        st.session_state.overdue_notifications_sent.discard(overdue_key)
                    # --- End Optional Clear ---
                else:
                    st.info(f"🖥️ {system} is being used by **{user_info['username']}**{reason_display}")
                    # --- Optional: Clear notification flag if conditions change ---
                    overdue_key = f"{system}_{user_info['email']}"
                    if overdue_key in st.session_state.overdue_notifications_sent:
                        st.session_state.overdue_notifications_sent.discard(overdue_key)
                    # --- End Optional Clear ---
            else:
                st.info(f"🖥️ {system} is being used by **{user_info['username']}**{reason_display}")
                # --- Optional: Clear notification flag if start_time/planned_duration missing ---
                overdue_key = f"{system}_{user_info['email']}"
                if overdue_key in st.session_state.overdue_notifications_sent:
                    st.session_state.overdue_notifications_sent.discard(overdue_key)
                # --- End Optional Clear ---
    # Process selected system (if any) - Main logic change here
    if selected_system:
        # Check current status for selected system
        user_active = selected_system in system_users and system_users[selected_system]['email'] == user_email
        system_in_use_by_user = user_active
        system_in_use_by_other = selected_system in system_users and system_users[selected_system]['username'] != username
        # Show timer for user's active session (if active)
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
                     # --- Change 2: Add option to extend time if overdue ---
                    st.subheader("Extend Session Time")
                    extension_options = {
                        "15 minutes": 15,
                        "30 minutes": 30,
                        "45 minutes": 45,
                        "1 hour": 60
                    }
                    selected_extension_label = st.selectbox(
                        "Add time:",
                        list(extension_options.keys()),
                        index=1, # Default to 30 min
                        key="extension_select"
                    )
                    extension_minutes = extension_options[selected_extension_label]
                    if st.button("Add Time"):
                        try:
                            with connection.cursor() as cursor:
                                # Update the planned_duration by adding the extension
                                cursor.execute("""
                                    UPDATE usage_log
                                    SET planned_duration = planned_duration + %s
                                    WHERE email = %s AND system_ip = %s AND end_time IS NULL
                                """, (extension_minutes, user_email, selected_system))
                            connection.commit()
                            st.success(f"Added {extension_minutes} minutes to your session on {selected_system}.")
                            st.rerun() # Refresh to show updated time
                        except Exception as e:
                            st.error(f"Failed to extend session: {e}")
                    # --- End Change 2 ---
                elif time_remaining is not None:
                    st.success(f"✅ You are using {selected_system} ({time_remaining} minutes remaining){reason_display}")
                else:
                    st.success(f"✅ You are using {selected_system}{reason_display}")
            else:
                st.success(f"✅ You are using {selected_system}{reason_display}")
        # Toggle button / Session control logic
        st.subheader("Usage Status")
        if system_in_use_by_other:
            st.warning(f"This system is currently being used by {system_users[selected_system]['username']}")
            status = "Inactive" # Cannot change status if in use by someone else
        else:
            # Determine default status for radio button
            default_status_index = 1 if user_active else 0
            status = st.radio(
                f"Mark {selected_system} as:",
                ["Inactive", "Active"],
                index=default_status_index,
                key="status_toggle",
                horizontal=True
            )
        # Handle status change
        if status == "Active" and not user_active and not system_in_use_by_other:
            # --- Key Change: Unified "Claim/Start" Logic for Free Systems ---
            # Check if the user is currently in the queue
            is_user_in_queue = user_queue_position > -1
            # Common elements for starting a session
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
                index=3  # Default to 1 hour
            )
            planned_duration = duration_options[selected_duration_label]
            st.subheader("Reason for Usage")
            usage_reason = ""
            # Pre-fill reason if claiming from queue
            if is_user_in_queue:
                # Simple way to get the reason from the queue for pre-filling
                queue_reason_for_claim = ""
                try:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT reason FROM usage_queue WHERE email = %s", (user_email,))
                        queue_reason_result = cursor.fetchone()
                        if queue_reason_result:
                            queue_reason_for_claim = queue_reason_result[0]
                except Exception as e:
                    st.warning(f"Could not fetch queue reason: {e}") # Log or handle error fetching reason
                usage_reason = st.text_area("Briefly explain why you need this system:", value=queue_reason_for_claim, key="usage_reason_claim_or_new")
                action_button_label = "Claim System and Start Session"
            else:
                usage_reason = st.text_area("Briefly explain why you need this system:", key="usage_reason_new", placeholder="Please specify why you need access...")
                action_button_label = "Start Session"
            # Action button (either Start or Claim)
            if st.button(action_button_label):
                if usage_reason.strip(): # Require reason
                    success = False
                    if is_user_in_queue:
                        # If user is in queue, remove them first, then start session
                        # Note: Potential race condition if multiple queued users try simultaneously.
                        # The database constraints or application logic should ideally prevent double booking.
                        remove_success = remove_from_queue(connection, user_email)
                        if remove_success:
                             start_success = start_session(connection, username, user_email, selected_system, planned_duration, usage_reason.strip())
                             if start_success:
                                 st.success(f"Claimed {selected_system} and started session ({selected_duration_label}). Removed from queue.")
                                 success = True
                             else:
                                 # Failed to start, try to re-add to queue? Or just notify?
                                 st.error("Failed to start session after removing from queue. You might need to re-join the queue.")
                                 # Optional: Re-add to queue if start failed? Requires careful handling.
                                 # add_to_queue(connection, username, user_email, usage_reason.strip()) # Risky without checks
                        else:
                             st.error("Failed to remove you from the queue.")
                    else:
                        # Standard start session (user was not in queue)
                        start_success = start_session(connection, username, user_email, selected_system, planned_duration, usage_reason.strip())
                        if start_success:
                            st.success(f"Started session for {selected_system} ({selected_duration_label})")
                            success = True
                        else:
                            st.error("Failed to start session")
                    if success:
                        # Refresh the app state to reflect changes
                        st.rerun()
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
    # ... (rest of the code like status display and history remains the same) ...
    st.subheader("Current System Status")
    if active_sessions:
        enhanced_sessions = []
        # --- Change 9: Use IST for 'now' calculation ---
        now = datetime.now(IST_TZ)
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
                    # Ensure start_time is treated as IST for calculation
                    if start_time.tzinfo is None:
                        start_time_ist = IST_TZ.localize(start_time)
                    else:
                        start_time_ist = start_time
                    active_since_td = now - start_time_ist
                    active_since = format_duration(active_since_td)
                except Exception as e:
                    st.warning(f"Error calculating active since: {e}")
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
        # --- Change 10: Consider displaying the raw datetime which is now in IST ---
        st.dataframe(status_df[["User", "System IP", "Start Time", "Active Since", "Status", "Planned Duration", "Time Remaining"]]) # Add "Reason" column here if desired, also showing Start Time
    else:
        st.info("No active sessions")
    st.subheader("Recent Usage History")
    history = get_usage_history(connection)
    if history:
        history_df = pd.DataFrame(history, columns=[
            "User", "Email", "System IP", "Start Time", "End Time", "Actual Duration (min)", "Planned Duration (min)", "Reason" # Add Reason
        ])
        # Optionally display Reason column in dataframe
        # --- Change 11: Consider displaying the raw datetime which is now in IST ---
        st.dataframe(history_df[["User", "System IP", "Start Time", "End Time", "Actual Duration (min)", "Planned Duration (min)", "Reason"]]) # Include Reason, also showing Start/End Time
    else:
        st.info("No usage history found")


def login_screen():
    st.header("🔒 System Usage Tracker")
    st.subheader("Please log in with Google to continue")
    if st.button("Log in with Google", type="primary"):
        st.login(provider="google")

# Main application logic
def run_app():
    # Initialize database (ensures tables are created)
    init_db() # This now sets the DB connection timezone
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