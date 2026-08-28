"""
routes/admin.py — Administrator Control Panel & Role-Based Access Control (RBAC)

SECURITY & INTERVIEW HIGHLIGHTS:
1. Strict Backend Authorization:
   - Every single route is protected with the `@admin_required` decorator.
   - We NEVER rely on client-side hiding alone; backend verifies `session.get('role') == 'admin'`.

2. Account Lockout & Unlock Management:
   - Admins can lock suspicious accounts or unlock users whose accounts were locked after 5 failed attempts.
   - When unlocked: `is_locked` is set to FALSE, `failed_logins` reset to 0, and `accounts.status` restored to 'active'.
   - Self-lockout protection: An admin cannot lock their own account.

3. Platform-Wide Oversight:
   - System user directory with active balances.
   - Global transaction monitoring across all users.
   - Complete historical audit trail.
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
    Admin Central Dashboard:
    - Aggregates platform KPIs (User count, locked accounts, total deposits, processed ledger volume).
    - Highlights recent user registrations and recent security events.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)

    try:
        # Platform Statistics
        cursor.execute("SELECT COUNT(*) AS total_users FROM users WHERE role = 'user'")
        total_users = cursor.fetchone()['total_users']

        cursor.execute("SELECT COUNT(*) AS locked_users FROM users WHERE is_locked = TRUE")
        locked_users = cursor.fetchone()['locked_users']

        cursor.execute("SELECT COALESCE(SUM(balance), 0) AS total_balance FROM accounts")
        total_balance = cursor.fetchone()['total_balance']

        cursor.execute("SELECT COUNT(*) AS total_txns FROM transactions WHERE status = 'success'")
        total_txns = cursor.fetchone()['total_txns']

        # Recent 5 Users
        cursor.execute(
            """SELECT u.id, u.username, u.email, u.full_name, u.role, u.is_locked, u.created_at,
                      a.account_number, a.balance, a.status AS account_status
               FROM users u
               LEFT JOIN accounts a ON u.id = a.user_id
               ORDER BY u.created_at DESC
               LIMIT 5"""
        )
        recent_users = cursor.fetchall()

        # Recent 5 Audit Logs
        cursor.execute(
            """SELECT al.id, al.action, al.details, al.ip_address, al.created_at,
                      u.username, u.full_name
               FROM audit_logs al
               LEFT JOIN users u ON al.user_id = u.id
               ORDER BY al.created_at DESC
               LIMIT 5"""
        )
        recent_logs = cursor.fetchall()

        # High-Priority: Pending Account Unlock Requests (submitted by currently locked users)
        cursor.execute(
            """SELECT al.id, al.user_id, al.details, al.created_at, al.ip_address,
                      u.username, u.full_name, u.email, u.is_locked,
                      a.account_number, a.balance
               FROM audit_logs al
               JOIN users u ON al.user_id = u.id
               LEFT JOIN accounts a ON u.id = a.user_id
               WHERE al.action = 'UNLOCK_REQUEST' AND u.is_locked = TRUE
               ORDER BY al.created_at DESC"""
        )
        pending_unlock_requests = cursor.fetchall()

        return render_template(
            'admin/dashboard.html',
            total_users=total_users,
            locked_users=locked_users,
            total_balance=total_balance,
            total_txns=total_txns,
            recent_users=recent_users,
            recent_logs=recent_logs,
            pending_unlock_requests=pending_unlock_requests
        )

    except Exception as e:
        flash("An error occurred while loading the admin dashboard.", "danger")
        return render_template('admin/dashboard.html', total_users=0, locked_users=0, total_balance=0, total_txns=0, recent_users=[], recent_logs=[], pending_unlock_requests=[])
    finally:
        cursor.close()
        conn.close()


@admin_bp.route('/users')
@admin_required
def users():
    """
    User Management:
    - Lists all registered users, roles, wallet account numbers, balances, and lock states.
    - Supports search by username, email, or account number.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)

    search_query = request.args.get('q', '').strip()
    status_filter = request.args.get('status', 'all').lower()

    try:
        sql = """
            SELECT u.id, u.username, u.email, u.full_name, u.role, u.is_locked,
                   u.failed_logins, u.created_at,
                   a.id AS account_id, a.account_number, a.balance, a.status AS account_status, a.daily_limit
            FROM users u
            LEFT JOIN accounts a ON u.id = a.user_id
            WHERE 1=1
        """
        params = []

        if status_filter == 'locked':
            sql += " AND u.is_locked = TRUE"
        elif status_filter == 'active':
            sql += " AND u.is_locked = FALSE"

        if search_query:
            sql += " AND (u.username LIKE %s OR u.email LIKE %s OR u.full_name LIKE %s OR a.account_number LIKE %s)"
            wildcard = f"%{search_query}%"
            params.extend([wildcard, wildcard, wildcard, wildcard])

        sql += " ORDER BY u.id ASC"

        cursor.execute(sql, tuple(params))
        user_list = cursor.fetchall()

        return render_template(
            'admin/users.html',
            users=user_list,
            search_query=search_query,
            status_filter=status_filter
        )

    except Exception as e:
        flash("An error occurred while retrieving the user directory.", "danger")
        return render_template('admin/users.html', users=[], search_query='', status_filter='all')
    finally:
        cursor.close()
        conn.close()


@admin_bp.route('/users/<int:user_id>/toggle-lock', methods=['POST'])
@admin_required
def toggle_lock(user_id):
    """
    Lock / Unlock User Account:
    - If user is locked: unlocks user (is_locked=FALSE), resets failed_logins to 0, sets account status to 'active'.
    - If user is active: locks user (is_locked=TRUE), sets account status to 'suspended'.
    - Prevents admin self-lockout.
    - Records detailed action in audit_logs.
    """
    current_admin_id = session['user_id']

    # 1. Prevent admin self-lockout
    if user_id == current_admin_id:
        flash("Action blocked: You cannot lock your own administrator account.", "danger")
        return redirect(url_for('admin.users'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)

    try:
        # Fetch target user
        cursor.execute("SELECT id, username, full_name, role, is_locked FROM users WHERE id = %s", (user_id,))
        target_user = cursor.fetchone()

        if not target_user:
            flash("Target user not found.", "danger")
            return redirect(url_for('admin.users'))

        if target_user['is_locked']:
            # UNLOCK USER
            cursor.execute(
                """UPDATE users
                   SET is_locked = FALSE, failed_logins = 0
                   WHERE id = %s""",
                (user_id,)
            )
            cursor.execute(
                """UPDATE accounts
                   SET status = 'active'
                   WHERE user_id = %s""",
                (user_id,)
            )
            conn.commit()

            # Record audit log
            log_audit_event(
                current_admin_id,
                'ACCOUNT_UNLOCKED',
                f"Admin '{session.get('username')}' unlocked user '{target_user['username']}' (ID: {user_id})"
            )
            flash(f"User '{target_user['username']}' has been successfully unlocked and restored to active status.", "success")
        else:
            # LOCK USER
            cursor.execute(
                """UPDATE users
                   SET is_locked = TRUE
                   WHERE id = %s""",
                (user_id,)
            )
            cursor.execute(
                """UPDATE accounts
                   SET status = 'suspended'
                   WHERE user_id = %s""",
                (user_id,)
            )
            conn.commit()

            # Record audit log
            log_audit_event(
                current_admin_id,
                'ACCOUNT_LOCKED',
                f"Admin '{session.get('username')}' manually locked user '{target_user['username']}' (ID: {user_id})"
            )
            flash(f"User '{target_user['username']}' has been locked and their wallet suspended.", "warning")

        return redirect(url_for('admin.users'))

    except Exception as e:
        conn.rollback()
        flash("An error occurred while modifying account lock status.", "danger")
        return redirect(url_for('admin.users'))
    finally:
        cursor.close()
        conn.close()


@admin_bp.route('/transactions')
@admin_required
def transactions():
    """
    Global Transaction Monitoring:
    - Displays all financial transactions across all platform accounts.
    - Filterable by type ('deposit', 'withdrawal', 'transfer') and status ('success', 'failed').
    - Searchable by user, note, or transaction reference.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)

    filter_type = request.args.get('type', 'all').lower()
    filter_status = request.args.get('status', 'all').lower()
    search_query = request.args.get('q', '').strip()

    try:
        sql = """
            SELECT t.id, t.transaction_ref, t.transaction_type, t.amount, t.status,
                   t.description, t.created_at, t.from_account_id, t.to_account_id,
                   a_from.account_number AS from_account_num,
                   u_from.username AS from_username,
                   u_from.full_name AS from_full_name,
                   a_to.account_number AS to_account_num,
                   u_to.username AS to_username,
                   u_to.full_name AS to_full_name
            FROM transactions t
            LEFT JOIN accounts a_from ON t.from_account_id = a_from.id
            LEFT JOIN users u_from ON a_from.user_id = u_from.id
            LEFT JOIN accounts a_to ON t.to_account_id = a_to.id
            LEFT JOIN users u_to ON a_to.user_id = u_to.id
            WHERE 1=1
        """
        params = []

        if filter_type in ['deposit', 'withdrawal', 'transfer']:
            sql += " AND t.transaction_type = %s"
            params.append(filter_type)

        if filter_status in ['success', 'failed']:
            sql += " AND t.status = %s"
            params.append(filter_status)

        if search_query:
            sql += """ AND (t.description LIKE %s OR t.transaction_ref LIKE %s
                            OR u_from.username LIKE %s OR u_to.username LIKE %s
                            OR a_from.account_number LIKE %s OR a_to.account_number LIKE %s)"""
            wildcard = f"%{search_query}%"
            params.extend([wildcard, wildcard, wildcard, wildcard, wildcard, wildcard])

        sql += " ORDER BY t.created_at DESC LIMIT 100"

        cursor.execute(sql, tuple(params))
        all_txns = cursor.fetchall()

        return render_template(
            'admin/transactions.html',
            transactions=all_txns,
            filter_type=filter_type,
            filter_status=filter_status,
            search_query=search_query
        )

    except Exception as e:
        flash("An error occurred while loading global transactions.", "danger")
        return render_template('admin/transactions.html', transactions=[], filter_type='all', filter_status='all', search_query='')
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
