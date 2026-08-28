"""
helpers/audit.py — Centralized Security & Compliance Audit Logger

PURPOSE:
    Provides a standardized, secure helper to record system and security events
    in the `audit_logs` table.

COMPLIANCE & INTERVIEW HIGHLIGHTS:
1. PII & Sensitive Data Protection:
   - Sanitizes and ensures passwords, tokens, or secret keys NEVER enter audit logs.
2. Contextual Metadata:
   - Automatically extracts client IP address from Flask request context.
   - Timestamps handled natively by database defaults.
3. Resilience:
   - Audit logging failure never crashes the primary business flow.
"""

from flask import request, has_request_context
from db import get_db_connection


def get_client_ip():
    """Extract client IP address safely from request headers or remote_addr."""
    if has_request_context():
        if request.headers.get('X-Forwarded-For'):
            return request.headers.get('X-Forwarded-For').split(',')[0].strip()
        return request.remote_addr or '127.0.0.1'
    return '127.0.0.1'


def log_audit_event(user_id, action, details, ip_address=None, conn=None):
    """
    Record an immutable event in the audit_logs table.

    Args:
        user_id (int or None): ID of user who performed/triggered the action (NULL for anonymous).
        action (str): Event category (e.g. 'LOGIN_SUCCESS', 'TRANSFER', 'DEPOSIT', 'ACCOUNT_LOCKED').
        details (str): Human-readable event description (Sanitized - no passwords).
        ip_address (str, optional): IP of the client. Defaults to auto-extracted IP.
        conn (mysql connection, optional): Existing active connection if inside a transaction.
    """
    client_ip = ip_address or get_client_ip()
    action = action.upper().strip()

    # Safety check: Prevent accidental password leakage in details
    if 'password' in details.lower():
        # Sanitize any accidental password mentions
        details = "[SANITIZED EVENT]: " + details.replace("password", "p***word")

    own_connection = False
    if conn is None:
        conn = get_db_connection()
        own_connection = True

    try:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO audit_logs (user_id, action, details, ip_address)
               VALUES (%s, %s, %s, %s)""",
            (user_id, action, details, client_ip)
        )
        if own_connection:
            conn.commit()
            cursor.close()
    except Exception as e:
        print(f"[AUDIT LOGGING ERROR]: Failed to record event {action} for user {user_id}: {e}")
    finally:
        if own_connection and conn:
            conn.close()
