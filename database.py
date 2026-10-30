import sqlite3
from datetime import datetime

DATABASE = "food_waste.db"


def get_db_connection():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def add_column_if_not_exists(connection, table_name, column_name, column_definition):
    columns = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    existing = {column["name"] for column in columns}
    if column_name not in existing:
        connection.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}"
        )


def create_tables():
    connection = get_db_connection()

    connection.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            phone TEXT,
            role TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS food_donations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            donor_id INTEGER NOT NULL,
            food_name TEXT NOT NULL,
            category TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            description TEXT,
            prepared_time TEXT,
            available_until TEXT,
            location TEXT NOT NULL,
            status TEXT DEFAULT 'Available',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (donor_id) REFERENCES users(id)
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS food_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            food_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            quantity_requested INTEGER NOT NULL,
            request_status TEXT DEFAULT 'Pending',
            request_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (food_id) REFERENCES food_donations(id),
            FOREIGN KEY (receiver_id) REFERENCES users(id)
        )
    """)

    # Safe migrations for databases created by the previous version.
    add_column_if_not_exists(connection, "users", "created_at", "TEXT")
    connection.execute("""UPDATE users SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP) WHERE created_at IS NULL""")

    add_column_if_not_exists(connection, "food_donations", "expiry_status",
                              "TEXT DEFAULT 'Fresh'")
    add_column_if_not_exists(connection, "food_donations", "pickup_time", "TEXT")
    add_column_if_not_exists(connection, "food_donations", "completed_at", "TEXT")
    add_column_if_not_exists(connection, "food_donations", "updated_at", "TEXT")

    add_column_if_not_exists(connection, "food_requests", "approved_at", "TEXT")
    add_column_if_not_exists(connection, "food_requests", "pickup_time", "TEXT")
    add_column_if_not_exists(connection, "food_requests", "completed_at", "TEXT")
    add_column_if_not_exists(connection, "food_requests", "updated_at", "TEXT")

    connection.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            notification_type TEXT DEFAULT 'General',
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_food_status
        ON food_donations(status)
    """)
    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_food_category
        ON food_donations(category)
    """)
    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_food_location
        ON food_donations(location)
    """)
    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_food_expiry
        ON food_donations(available_until)
    """)
    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_requests_status
        ON food_requests(request_status)
    """)
    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_notifications_user
        ON notifications(user_id)
    """)

    connection.commit()
    connection.close()


def update_expired_food():
    """Update freshness labels and make past-expiry available food unavailable."""
    connection = get_db_connection()
    now = datetime.now()

    rows = connection.execute("""
        SELECT id, available_until, status
        FROM food_donations
        WHERE available_until IS NOT NULL
          AND available_until != ''
          AND status IN ('Available', 'Pickup Scheduled')
    """).fetchall()

    for row in rows:
        try:
            expiry = datetime.strptime(row["available_until"], "%Y-%m-%dT%H:%M")
        except (ValueError, TypeError):
            continue

        hours = (expiry - now).total_seconds() / 3600

        if hours <= 0 and row["status"] == "Available":
            connection.execute("""
                UPDATE food_donations
                SET status = 'Expired',
                    expiry_status = 'Expired',
                    updated_at = ?
                WHERE id = ?
            """, (now.strftime("%Y-%m-%d %H:%M:%S"), row["id"]))
        elif hours <= 6:
            connection.execute("""
                UPDATE food_donations
                SET expiry_status = 'Expiring Soon',
                    updated_at = ?
                WHERE id = ?
            """, (now.strftime("%Y-%m-%d %H:%M:%S"), row["id"]))
        else:
            connection.execute("""
                UPDATE food_donations
                SET expiry_status = 'Fresh',
                    updated_at = ?
                WHERE id = ?
            """, (now.strftime("%Y-%m-%d %H:%M:%S"), row["id"]))

    connection.commit()
    connection.close()


def create_notification(user_id, message, notification_type="General"):
    connection = get_db_connection()
    connection.execute("""
        INSERT INTO notifications (user_id, message, notification_type)
        VALUES (?, ?, ?)
    """, (user_id, message, notification_type))
    connection.commit()
    connection.close()


def mark_notification_read(notification_id, user_id):
    connection = get_db_connection()
    connection.execute("""
        UPDATE notifications
        SET is_read = 1
        WHERE id = ? AND user_id = ?
    """, (notification_id, user_id))
    connection.commit()
    connection.close()


def complete_donation(food_id):
    connection = get_db_connection()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    connection.execute("""
        UPDATE food_donations
        SET status = 'Completed',
            expiry_status = 'Completed',
            completed_at = ?,
            updated_at = ?
        WHERE id = ?
    """, (now, now, food_id))
    connection.commit()
    connection.close()


if __name__ == "__main__":
    create_tables()
    update_expired_food()
    print("FoodShare database initialized successfully.")
