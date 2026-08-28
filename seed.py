"""
seed.py — Alternative Python-based seeder for SecurePay

NOTE: For development, prefer using seed.sql instead:
    mysql -u root -p securepay_db < seed.sql

This Python script is useful when you want to:
  - Generate fresh password hashes (seed.sql has pre-computed ones)
  - Add custom test data programmatically
  - Reset just the admin user without reloading everything

USAGE:
    python seed.py
"""

from werkzeug.security import generate_password_hash
from db import get_db_connection


def seed_admin():
    """Insert the default admin user if one doesn't already exist."""

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Check if admin already exists
        cursor.execute("SELECT id FROM users WHERE username = %s", ('admin',))
        if cursor.fetchone():
            print("Admin user already exists. Skipping.")
            return

        # ----- Begin transaction (both inserts succeed or both fail) -----

        # 1. Create admin user with hashed password
        password_hash = generate_password_hash('admin123')
        cursor.execute(
            """INSERT INTO users (username, email, password_hash, full_name, role)
               VALUES (%s, %s, %s, %s, %s)""",
            ('admin', 'admin@securepay.com', password_hash, 'System Admin', 'admin')
        )

        # 2. Get the auto-generated user ID
        admin_id = cursor.lastrowid

        # 3. Create the admin's wallet account
        #    Account number format: ACC + zero-padded ID → ACC00001
        account_number = f"ACC{admin_id:05d}"
        cursor.execute(
            """INSERT INTO accounts (user_id, account_number, balance)
               VALUES (%s, %s, %s)""",
            (admin_id, account_number, 0.00)
        )

        # 4. Commit — both user and account are saved together
        conn.commit()

        print("Admin user created successfully!")
        print(f"  Username : admin")
        print(f"  Password : admin123")
        print(f"  Account  : {account_number}")
        print(f"  WARNING  : Change the password after first login!")

    except Exception as e:
        # If anything fails, undo everything
        conn.rollback()
        print(f"Error creating admin: {e}")

    finally:
        # Always clean up database resources
        cursor.close()
        conn.close()


if __name__ == '__main__':
    seed_admin()
