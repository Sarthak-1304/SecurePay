"""
routes/wallet.py — Digital Wallet Operations (Dashboard, Deposit, Withdraw)

KEY TECHNICAL & INTERVIEW HIGHLIGHTS:
1. SQL Transactions with Row-Level Locking:
   - Every balance modification uses `SELECT ... FOR UPDATE` inside an explicit transaction.
   - Row-level lock prevents Race Conditions and Double-Spending attacks during concurrent requests.
   - Atomicity guaranteed: balance update + transaction audit record either BOTH succeed (COMMIT)
     or BOTH roll back (ROLLBACK).

2. Safe Monetary Arithmetic:
   - Uses Python's `decimal.Decimal` to avoid binary floating-point rounding errors.
   - Validates positive amounts and enforces max 2 decimal places (cents/paise precision).

3. Defense-in-Depth Authorization:
   - Enforces `@login_required`.
   - Binds all queries to `session['user_id']`, preventing Insecure Direct Object References (IDOR).
   - Verifies account status is 'active' before allowing financial operations.
"""

import uuid
from decimal import Decimal, InvalidOperation
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from db import get_db_connection
from helpers.decorators import login_required

wallet_bp = Blueprint('wallet', __name__)


def get_client_ip():
    """Extract client IP address safely."""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    return request.remote_addr or '127.0.0.1'


def parse_and_validate_amount(amount_str):
    """
    Safely parse and validate a monetary input string into a Decimal.

    Rules:
    - Must be a valid decimal number.
    - Must be greater than 0.
    - Cannot have more than 2 decimal places (currency precision).
    - Maximum single deposit/withdrawal limit: ₹1,000,000.00 (sanity check).

    Returns:
        tuple: (Decimal amount or None, error_message or None)
    """
    if not amount_str or not amount_str.strip():
        return None, "Please enter an amount."

    try:
        amount = Decimal(amount_str.strip())
    except (InvalidOperation, TypeError, ValueError):
        return None, "Invalid amount format. Please enter a valid number (e.g., 500.00)."

    if amount <= Decimal('0.00'):
        return None, "Amount must be greater than zero."

    # Verify maximum 2 decimal places (e.g. 500.25 is valid, 500.255 is invalid)
    if amount.as_tuple().exponent < -2:
        return None, "Amount cannot have more than 2 decimal places."

    if amount > Decimal('1000000.00'):
        return None, "Maximum single transaction limit is ₹1,000,000.00."

    return amount, None


@wallet_bp.route('/dashboard')
@login_required
def dashboard():
    """
    User Dashboard:
    - Fetches the logged-in user's wallet account (account number, balance, status).
    - Fetches recent transactions (latest 5) for quick overview.
    """
    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)

    try:
        # Fetch account details for this specific user
        cursor.execute(
            """SELECT id, account_number, balance, status, daily_limit, created_at
               FROM accounts
               WHERE user_id = %s""",
            (user_id,)
        )
        account = cursor.fetchone()

        if not account:
            flash("No wallet account found for your profile. Please contact support.", "danger")
            return render_template('wallet/dashboard.html', account=None, recent_transactions=[])

        # Fetch recent 5 transactions involving this account
        account_id = account['id']
        cursor.execute(
            """SELECT t.id, t.transaction_ref, t.transaction_type, t.amount, t.status,
                      t.description, t.created_at, t.from_account_id, t.to_account_id,
                      u_from.username AS from_username,
                      u_to.username AS to_username
               FROM transactions t
               LEFT JOIN accounts a_from ON t.from_account_id = a_from.id
               LEFT JOIN users u_from ON a_from.user_id = u_from.id
               LEFT JOIN accounts a_to ON t.to_account_id = a_to.id
               LEFT JOIN users u_to ON a_to.user_id = u_to.id
               WHERE t.from_account_id = %s OR t.to_account_id = %s
               ORDER BY t.created_at DESC
               LIMIT 5""",
            (account_id, account_id)
        )
        recent_transactions = cursor.fetchall()

        return render_template(
            'wallet/dashboard.html',
            account=account,
            recent_transactions=recent_transactions
        )

    except Exception as e:
        flash("An error occurred while loading your dashboard.", "danger")
        return render_template('wallet/dashboard.html', account=None, recent_transactions=[])
    finally:
        cursor.close()
        conn.close()


@wallet_bp.route('/deposit', methods=['GET', 'POST'])
@login_required
def deposit():
    """
    Deposit Funds:
    - Validates positive amount.
    - Locks account row (`SELECT ... FOR UPDATE`).
    - Verifies account status is active.
    - Increases account balance.
    - Records deposit in `transactions` table.
    - Logs event in `audit_logs`.
    - Atomically commits the SQL transaction.
    """
    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)

    # Fetch basic account info for GET request
    cursor.execute("SELECT id, account_number, balance, status FROM accounts WHERE user_id = %s", (user_id,))
    account = cursor.fetchone()

    if not account:
        cursor.close()
        conn.close()
        flash("No wallet found.", "danger")
        return redirect(url_for('wallet.dashboard'))

    if request.method == 'POST':
        raw_amount = request.form.get('amount', '')
        description = request.form.get('description', '').strip() or "Deposit to wallet"
        client_ip = get_client_ip()

        # 1. Validate amount
        amount, error = parse_and_validate_amount(raw_amount)
        if error:
            flash(error, "danger")
            cursor.close()
            conn.close()
            return render_template('wallet/deposit.html', account=account)

        try:
            # 2. Lock account row with FOR UPDATE (Row-level locking)
            cursor.execute(
                """SELECT id, account_number, balance, status
                   FROM accounts
                   WHERE user_id = %s
                   FOR UPDATE""",
                (user_id,)
            )
            locked_account = cursor.fetchone()

            if not locked_account:
                conn.rollback()
                flash("Wallet account not found.", "danger")
                return redirect(url_for('wallet.dashboard'))

            if locked_account['status'] != 'active':
                conn.rollback()
                flash(f"Cannot deposit: Your account is currently {locked_account['status']}.", "danger")
                return render_template('wallet/deposit.html', account=locked_account)

            account_id = locked_account['id']

            # 4. Update balance
            cursor.execute(
                """UPDATE accounts
                   SET balance = balance + %s
                   WHERE id = %s""",
                (amount, account_id)
            )

            # 5. Insert transaction record (from_account_id is NULL for external deposit)
            txn_ref = str(uuid.uuid4())
            cursor.execute(
                """INSERT INTO transactions
                   (transaction_ref, from_account_id, to_account_id, transaction_type, amount, status, description)
                   VALUES (%s, NULL, %s, 'deposit', %s, 'success', %s)""",
                (txn_ref, account_id, amount, description)
            )

            # 6. Audit log entry
            cursor.execute(
                """INSERT INTO audit_logs (user_id, action, details, ip_address)
                   VALUES (%s, 'DEPOSIT', %s, %s)""",
                (user_id, f"Deposited ₹{amount:,.2f} into account {locked_account['account_number']}. Ref: {txn_ref}", client_ip)
            )

            # 7. COMMIT TRANSACTION
            conn.commit()

            flash(f"Successfully deposited ₹{amount:,.2f}! (Ref: {txn_ref[:8]}...)", "success")
            return redirect(url_for('wallet.dashboard'))

        except Exception as e:
            conn.rollback()
            print(f"[ERROR in deposit]: {e}")
            flash("Deposit failed due to a system error. Your balance was not changed.", "danger")
            return render_template('wallet/deposit.html', account=account)
        finally:
            cursor.close()
            conn.close()

    cursor.close()
    conn.close()
    return render_template('wallet/deposit.html', account=account)


@wallet_bp.route('/withdraw', methods=['GET', 'POST'])
@login_required
def withdraw():
    """
    Withdraw Funds:
    - Validates positive amount.
    - Locks account row (`SELECT ... FOR UPDATE`).
    - Verifies account status is active.
    - Validates sufficient balance.
    - Decreases account balance.
    - Records withdrawal in `transactions` table.
    - Logs event in `audit_logs`.
    - Atomically commits the SQL transaction.
    """
    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)

    cursor.execute("SELECT id, account_number, balance, status FROM accounts WHERE user_id = %s", (user_id,))
    account = cursor.fetchone()

    if not account:
        cursor.close()
        conn.close()
        flash("No wallet found.", "danger")
        return redirect(url_for('wallet.dashboard'))

    if request.method == 'POST':
        raw_amount = request.form.get('amount', '')
        description = request.form.get('description', '').strip() or "Withdrawal from wallet"
        client_ip = get_client_ip()

        # 1. Validate amount format
        amount, error = parse_and_validate_amount(raw_amount)
        if error:
            flash(error, "danger")
            cursor.close()
            conn.close()
            return render_template('wallet/withdraw.html', account=account)

        try:
            # 2. Lock account row with FOR UPDATE to prevent race conditions
            cursor.execute(
                """SELECT id, account_number, balance, status
                   FROM accounts
                   WHERE user_id = %s
                   FOR UPDATE""",
                (user_id,)
            )
            locked_account = cursor.fetchone()

            if not locked_account:
                conn.rollback()
                flash("Wallet account not found.", "danger")
                return redirect(url_for('wallet.dashboard'))

            if locked_account['status'] != 'active':
                conn.rollback()
                flash(f"Cannot withdraw: Your account is currently {locked_account['status']}.", "danger")
                return render_template('wallet/withdraw.html', account=locked_account)

            current_balance = Decimal(str(locked_account['balance']))

            # 4. Check sufficient balance
            if current_balance < amount:
                conn.rollback()
                flash(f"Insufficient funds! Your available balance is ₹{current_balance:,.2f}, but you requested ₹{amount:,.2f}.", "danger")
                return render_template('wallet/withdraw.html', account=locked_account)

            account_id = locked_account['id']

            # 5. Deduct balance
            cursor.execute(
                """UPDATE accounts
                   SET balance = balance - %s
                   WHERE id = %s""",
                (amount, account_id)
            )

            # 6. Insert transaction record (to_account_id is NULL for external withdrawal)
            txn_ref = str(uuid.uuid4())
            cursor.execute(
                """INSERT INTO transactions
                   (transaction_ref, from_account_id, to_account_id, transaction_type, amount, status, description)
                   VALUES (%s, %s, NULL, 'withdrawal', %s, 'success', %s)""",
                (txn_ref, account_id, amount, description)
            )

            # 7. Audit log entry
            cursor.execute(
                """INSERT INTO audit_logs (user_id, action, details, ip_address)
                   VALUES (%s, 'WITHDRAWAL', %s, %s)""",
                (user_id, f"Withdrew ₹{amount:,.2f} from account {locked_account['account_number']}. Ref: {txn_ref}", client_ip)
            )

            # 8. COMMIT TRANSACTION
            conn.commit()

            flash(f"Successfully withdrew ₹{amount:,.2f}! (Ref: {txn_ref[:8]}...)", "success")
            return redirect(url_for('wallet.dashboard'))

        except Exception as e:
            conn.rollback()
            print(f"[ERROR in withdraw]: {e}")
            flash("Withdrawal failed due to a system error. Your balance was not changed.", "danger")
            return render_template('wallet/withdraw.html', account=account)
        finally:
            cursor.close()
            conn.close()

    cursor.close()
    conn.close()
    return render_template('wallet/withdraw.html', account=account)
