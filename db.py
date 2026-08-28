"""
db.py — Database connection helper
"""

import os
import mysql.connector
from config import Config


def get_db_connection():
    """
    Create and return a secure MySQL database connection.

    Works with Aiven MySQL using SSL/TLS.
    """

    connection = mysql.connector.connect(
        host=Config.MYSQL_HOST,
        port=Config.MYSQL_PORT,
        user=Config.MYSQL_USER,
        password=Config.MYSQL_PASSWORD,
        database=Config.MYSQL_DATABASE,

        # Aiven requires SSL/TLS
        ssl_ca=os.getenv("MYSQL_SSL_CA"),
        ssl_verify_cert=True,
    )

    return connection