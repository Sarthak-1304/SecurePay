"""
routes/admin.py — Administrator Audit & Oversight Routes

SECURITY & INTERVIEW HIGHLIGHTS:
1. Role-Based Access Control (RBAC):
   - Every route in this blueprint is strictly protected by `@admin_required`.
   - Prevents unauthorized access or privilege escalation.

2. Comprehensive Compliance & Audit Trail:
   - Provides a searchable, filterable system-wide security log viewer (`/admin/audit-logs`).
   - Filters by action type, date range, and keyword search (username, details, IP).
   - Immutable historical view into logins, failed attempts, account locking, and transfers.
"""

from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from db import get_db_connection
from helpers.decorators import admin_required
from helpers.audit import log_audit_event

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.route('/dashboard')
@admin_required
def dashboard():
    """
    Admin Overview Dashboard:
    - Displays platform metrics: Total Registered Users, Total Accounts, Total Volume, Locked Users.
    - Displays latest 10 system audit events.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)

    try:
        # 1. Platform Statistics
        cursor.execute("SELECT COUNT(*) AS total_users FROM users WHERE role = 'user'")
        total_users = cursor.fetchone()['total_users']

        cursor.execute("SELECT COUNT(*) AS locked_users FROM users WHERE is_locked = TRUE")
        locked_users = cursor.fetchone()['locked_users']

        cursor.execute("SELECT COALESCE(SUM(balance), 0) AS total_balance FROM accounts")
        total_balance = cursor.fetchone()['total_balance']

        cursor.execute("SELECT COUNT(*) AS total_txns FROM transactions WHERE status = 'success'")
        total_txns = cursor.fetchone()['total_txns']

        # 2. Latest 10 Audit Logs
        cursor.execute(
            """SELECT al.id, al.action, al.details, al.ip_address, al.created_at,
                      u.username, u.full_name, u.role
               FROM audit_logs al
               LEFT JOIN users u ON al.user_id = u.id
               ORDER BY al.created_at DESC
               LIMIT 10"""
        )
        recent_logs = cursor.fetchall()

        return render_template(
            'admin/dashboard.html',
            total_users=total_users,
            locked_users=locked_users,
            total_balance=total_balance,
            total_txns=total_txns,
            recent_logs=recent_logs
        )

    except Exception as e:
        flash("An error occurred while loading the admin dashboard.", "danger")
        return render_template('admin/dashboard.html', total_users=0, locked_users=0, total_balance=0, total_txns=0, recent_logs=[])
    finally:
        cursor.close()
        conn.close()


@admin_bp.route('/audit-logs')
@admin_required
def audit_logs():
    """
    System-Wide Audit Log Viewer:
    - Lists all recorded security & financial events.
    - Filterable by action type, date range, and keyword search.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)

    action_filter = request.args.get('action', 'all').strip().upper()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    search_query = request.args.get('q', '').strip()

    try:
        sql = """
            SELECT al.id, al.action, al.details, al.ip_address, al.created_at,
                   u.username, u.full_name, u.role
            FROM audit_logs al
            LEFT JOIN users u ON al.user_id = u.id
            WHERE 1=1
        """
        params = []

        if action_filter and action_filter != 'ALL':
            sql += " AND al.action = %s"
            params.append(action_filter)

        if date_from:
            sql += " AND DATE(al.created_at) >= %s"
            params.append(date_from)

        if date_to:
            sql += " AND DATE(al.created_at) <= %s"
            params.append(date_to)

        if search_query:
            sql += " AND (al.details LIKE %s OR al.ip_address LIKE %s OR u.username LIKE %s OR u.full_name LIKE %s)"
            wildcard = f"%{search_query}%"
            params.extend([wildcard, wildcard, wildcard, wildcard])

        sql += " ORDER BY al.created_at DESC LIMIT 100"

        cursor.execute(sql, tuple(params))
        logs = cursor.fetchall()

        # Fetch distinct action types for the filter dropdown
        cursor.execute("SELECT DISTINCT action FROM audit_logs ORDER BY action")
        action_types = [row['action'] for row in cursor.fetchall()]

        return render_template(
            'admin/audit_logs.html',
            logs=logs,
            action_types=action_types,
            action_filter=action_filter,
            date_from=date_from,
            date_to=date_to,
            search_query=search_query
        )

    except Exception as e:
        flash("An error occurred while loading audit logs.", "danger")
        return render_template('admin/audit_logs.html', logs=[], action_types=[], action_filter='ALL', date_from='', date_to='', search_query='')
    finally:
        cursor.close()
        conn.close()
