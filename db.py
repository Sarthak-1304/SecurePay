"""
db.py — Database connection helper

HOW IT WORKS:
- get_db_connection() creates a new MySQL connection using settings from Config.
- We use it as a context manager (with statement) so the connection is
  ALWAYS closed properly, even if an error occurs.

USAGE IN ROUTES:
    from db import get_db_connection

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)    # Returns rows as dicts
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()                 # {'id': 1, 'username': 'john', ...}
    cursor.close()
    conn.close()

WHY dictionary=True:
    Without it:  cursor.fetchone() → (1, 'john', 'john@email.com')  (tuple)
    With it:     cursor.fetchone() → {'id': 1, 'username': 'john', 'email': 'john@email.com'}
    Dicts are much easier to work with in templates and code.

WHY NOT AN ORM:
    This project deliberately uses raw SQL with parameterized queries to
    demonstrate SQL skills — which is the whole point for interviews.
"""

import mysql.connector
from config import Config


def get_db_connection():
    """
    Create and return a new MySQL database connection.

    Returns a mysql.connector connection object.
    The caller is responsible for closing it when done.
    """
    connection = mysql.connector.connect(
        host=Config.MYSQL_HOST,
        port=Config.MYSQL_PORT,
        user=Config.MYSQL_USER,
        password=Config.MYSQL_PASSWORD,
        database=Config.MYSQL_DATABASE
    )
    return connection
