"""
routes/wallet.py — Digital Wallet Operations (Dashboard, Deposit, Withdraw, Transfer, History)

KEY TECHNICAL & INTERVIEW HIGHLIGHTS:
1. Two-Account Atomic SQL Transfer:
   - Debit from sender and credit to receiver inside a single atomic SQL transaction.
   - If ANY check or query fails, `conn.rollback()` executes — sender never loses funds without receiver receiving them.

2. Deadlock Prevention via Deterministic Lock Ordering:
   - When transferring money between Account A and Account B, locking them in arbitrary order can cause
     a circular wait (Deadlock) if B is simultaneously transferring to A.
   - We sort account IDs (`sorted([sender_id, receiver_id])`) and lock them in ascending numerical order (`ORDER BY id FOR UPDATE`).
   - This eliminates circular wait conditions mathematically.

3. Daily Transaction Limit Enforcement:
   - Aggregates today's outgoing transfers + withdrawals using `SUM(amount)` and `DATE(created_at) = CURDATE()`.
   - Rejects outgoing transactions exceeding the user's `daily_limit` (default ₹50,000.00).

4. Safe Decimal Precision & Defense-in-Depth:
   - Exact monetary arithmetic using Python's `decimal.Decimal`.
   - Immutable financial transaction logs with UUID reference keys.
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
    - Maximum single transaction limit: ₹1,000,000.00.

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


def get_daily_spent(cursor, account_id):
    """
    Calculate the total outgoing amount spent today by an account (withdrawals + transfers sent).
    """
    cursor.execute(
        """SELECT COALESCE(SUM(amount), 0) AS total_spent
           FROM transactions
           WHERE from_account_id = %s
             AND status = 'success'
             AND DATE(created_at) = CURDATE()""",
        (account_id,)
    )
    row = cursor.fetchone()
    return Decimal(str(row['total_spent'])) if row else Decimal('0.00')


@wallet_bp.route('/dashboard')
@login_required
def dashboard():
    """
    User Dashboard:
    - Fetches the logged-in user's wallet account (account number, balance, status, daily limit).
    - Calculates today's spent amount towards the daily limit.
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
            return render_template('wallet/dashboard.html', account=None, recent_transactions=[], daily_spent=0, remaining_limit=0)

        account_id = account['id']
        daily_spent = get_daily_spent(cursor, account_id)
        daily_limit = Decimal(str(account['daily_limit']))
        remaining_limit = max(Decimal('0.00'), daily_limit - daily_spent)

        # Fetch recent 5 transactions involving this account
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
            recent_transactions=recent_transactions,
            daily_spent=daily_spent,
            remaining_limit=remaining_limit
        )

    except Exception as e:
        flash("An error occurred while loading your dashboard.", "danger")
        return render_template('wallet/dashboard.html', account=None, recent_transactions=[], daily_spent=0, remaining_limit=0)
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

    cursor.execute("SELECT id, account_number, balance, status FROM accounts WHERE user_id = %s", (user_id,))
    account = cursor.fetchone()

    if not account:
        cursor.close()
        conn.close()
        flash("No wallet found.", "danger")
        return redirect(url_for('wallet.dashboard'))

    if request.method == 'POST':
        raw_amount = request.form.get('amount', '')
        description = (request.form.get('description', '').strip()[:255]) or "Deposit to wallet"
        client_ip = get_client_ip()

        # 1. Validate amount
        amount, error = parse_and_validate_amount(raw_amount)
        if error:
            flash(error, "danger")
            cursor.close()
            conn.close()
            return render_template('wallet/deposit.html', account=account)

        try:
            # 2. Lock account row with FOR UPDATE
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

            # 3. Update balance
            cursor.execute(
                """UPDATE accounts
                   SET balance = balance + %s
                   WHERE id = %s""",
                (amount, account_id)
            )

            # 4. Insert transaction record (from_account_id is NULL for external deposit)
            txn_ref = str(uuid.uuid4())
            cursor.execute(
                """INSERT INTO transactions
                   (transaction_ref, from_account_id, to_account_id, transaction_type, amount, status, description)
                   VALUES (%s, NULL, %s, 'deposit', %s, 'success', %s)""",
                (txn_ref, account_id, amount, description)
            )

            # 5. Audit log entry
            cursor.execute(
                """INSERT INTO audit_logs (user_id, action, details, ip_address)
                   VALUES (%s, 'DEPOSIT', %s, %s)""",
                (user_id, f"Deposited ₹{amount:,.2f} into account {locked_account['account_number']}. Ref: {txn_ref}", client_ip)
            )

            # 6. COMMIT TRANSACTION
            conn.commit()

            flash(f"Successfully deposited ₹{amount:,.2f}! (Ref: {txn_ref[:8]}...)", "success")
            return redirect(url_for('wallet.dashboard'))

        except Exception as e:
            conn.rollback()
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
    - Checks daily spending limit.
    - Decreases account balance.
    - Records withdrawal in `transactions` table.
    - Logs event in `audit_logs`.
    - Atomically commits the SQL transaction.
    """
    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)

    cursor.execute("SELECT id, account_number, balance, status, daily_limit FROM accounts WHERE user_id = %s", (user_id,))
    account = cursor.fetchone()

    if not account:
        cursor.close()
        conn.close()
        flash("No wallet found.", "danger")
        return redirect(url_for('wallet.dashboard'))

    if request.method == 'POST':
        raw_amount = request.form.get('amount', '')
        description = (request.form.get('description', '').strip()[:255]) or "Withdrawal from wallet"
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
                """SELECT id, account_number, balance, status, daily_limit
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

            account_id = locked_account['id']
            current_balance = Decimal(str(locked_account['balance']))

            # 3. Check sufficient balance
            if current_balance < amount:
                conn.rollback()
                flash(f"Insufficient funds! Your available balance is ₹{current_balance:,.2f}, but you requested ₹{amount:,.2f}.", "danger")
                return render_template('wallet/withdraw.html', account=locked_account)

            # 4. Check Daily Limit
            daily_spent = get_daily_spent(cursor, account_id)
            daily_limit = Decimal(str(locked_account['daily_limit']))
            if daily_spent + amount > daily_limit:
                conn.rollback()
                remaining = max(Decimal('0.00'), daily_limit - daily_spent)
                flash(f"Daily transaction limit exceeded! You have spent ₹{daily_spent:,.2f} of your ₹{daily_limit:,.2f} limit today. Remaining allowance: ₹{remaining:,.2f}.", "danger")
                return render_template('wallet/withdraw.html', account=locked_account)

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
            flash("Withdrawal failed due to a system error. Your balance was not changed.", "danger")
            return render_template('wallet/withdraw.html', account=account)
        finally:
            cursor.close()
            conn.close()

    cursor.close()
    conn.close()
    return render_template('wallet/withdraw.html', account=account)


@wallet_bp.route('/transfer', methods=['GET', 'POST'])
@login_required
def transfer():
    """
    Atomic Peer-to-Peer Transfer:
    1. Identifies sender and receiver.
    2. Validates positive amount.
    3. Checks recipient existence and status.
    4. Prevents self-transfer.
    5. Locks both accounts in sorted ID order (Deadlock Prevention).
    6. Verifies sender has sufficient balance.
    7. Verifies daily limit compliance.
    8. Atomically debits sender and credits receiver.
    9. Creates immutable transaction ledger record.
    10. Creates audit log.
    11. Commits on success or rolls back completely on any error.
    """
    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)

    cursor.execute("SELECT id, account_number, balance, status, daily_limit FROM accounts WHERE user_id = %s", (user_id,))
    sender_account = cursor.fetchone()

    if not sender_account:
        cursor.close()
        conn.close()
        flash("No wallet found.", "danger")
        return redirect(url_for('wallet.dashboard'))

    daily_spent = get_daily_spent(cursor, sender_account['id'])
    daily_limit = Decimal(str(sender_account['daily_limit']))
    remaining_limit = max(Decimal('0.00'), daily_limit - daily_spent)

    if request.method == 'POST':
        recipient_input = request.form.get('recipient', '').strip()
        raw_amount = request.form.get('amount', '')
        description = (request.form.get('description', '').strip()[:255]) or "P2P Money Transfer"
        client_ip = get_client_ip()

        # 1. Validate Amount
        amount, error = parse_and_validate_amount(raw_amount)
        if error:
            flash(error, "danger")
            cursor.close()
            conn.close()
            return render_template('wallet/transfer.html',
                                   account=sender_account,
                                   daily_spent=daily_spent,
                                   remaining_limit=remaining_limit,
                                   recipient=recipient_input)

        if not recipient_input:
            flash("Please enter the recipient's username, email, or account number.", "danger")
            cursor.close()
            conn.close()
            return render_template('wallet/transfer.html',
                                   account=sender_account,
                                   daily_spent=daily_spent,
                                   remaining_limit=remaining_limit)

        try:
            # 2. Identify Recipient Account & User
            cursor.execute(
                """SELECT a.id AS account_id, a.account_number, a.user_id, a.status AS account_status,
                          u.username, u.full_name, u.is_locked
                   FROM accounts a
                   JOIN users u ON a.user_id = u.id
                   WHERE a.account_number = %s OR u.username = %s OR u.email = %s""",
                (recipient_input, recipient_input, recipient_input.lower())
            )
            recipient = cursor.fetchone()

            if not recipient:
                flash(f"Recipient '{recipient_input}' not found. Please verify username, email, or account number.", "danger")
                return render_template('wallet/transfer.html',
                                       account=sender_account,
                                       daily_spent=daily_spent,
                                       remaining_limit=remaining_limit,
                                       recipient=recipient_input)

            # 3. Prevent Self-Transfer
            if recipient['account_id'] == sender_account['id']:
                flash("You cannot transfer money to your own wallet.", "danger")
                return render_template('wallet/transfer.html',
                                       account=sender_account,
                                       daily_spent=daily_spent,
                                       remaining_limit=remaining_limit)

            # 4. Check Recipient Account Status
            if recipient['account_status'] != 'active' or recipient['is_locked']:
                flash(f"Cannot transfer: Recipient's account is currently inactive or suspended.", "danger")
                return render_template('wallet/transfer.html',
                                       account=sender_account,
                                       daily_spent=daily_spent,
                                       remaining_limit=remaining_limit,
                                       recipient=recipient_input)

            # =========================================================================
            # 5. DEADLOCK PREVENTION: Deterministic Row-Level Lock Ordering
            # =========================================================================
            # We sort the two account IDs so locks are ALWAYS acquired in ascending order.
            # This mathematically prevents deadlock cycles if User A -> B and User B -> A happen simultaneously.
            # =========================================================================
            sender_acc_id = sender_account['id']
            receiver_acc_id = recipient['account_id']
            first_lock_id, second_lock_id = sorted([sender_acc_id, receiver_acc_id])

            cursor.execute(
                """SELECT id, account_number, balance, status, daily_limit
                   FROM accounts
                   WHERE id IN (%s, %s)
                   ORDER BY id
                   FOR UPDATE""",
                (first_lock_id, second_lock_id)
            )
            locked_rows = cursor.fetchall()
            locked_map = {row['id']: row for row in locked_rows}

            locked_sender = locked_map.get(sender_acc_id)
            locked_receiver = locked_map.get(receiver_acc_id)

            if not locked_sender or not locked_receiver:
                conn.rollback()
                flash("Account retrieval failed during lock. Transfer cancelled.", "danger")
                return redirect(url_for('wallet.transfer'))

            if locked_sender['status'] != 'active':
                conn.rollback()
                flash("Your account is not active. Transfer cancelled.", "danger")
                return redirect(url_for('wallet.dashboard'))

            if locked_receiver['status'] != 'active':
                conn.rollback()
                flash("Recipient account is not active. Transfer cancelled.", "danger")
                return redirect(url_for('wallet.transfer'))

            # 6. Verify Sufficient Balance
            sender_current_balance = Decimal(str(locked_sender['balance']))
            if sender_current_balance < amount:
                conn.rollback()
                flash(f"Insufficient balance! Available: ₹{sender_current_balance:,.2f}, Requested: ₹{amount:,.2f}.", "danger")
                return render_template('wallet/transfer.html',
                                       account=locked_sender,
                                       daily_spent=sender_daily_spent,
                                       remaining_limit=max(Decimal('0.00'), sender_daily_limit - sender_daily_spent),
                                       recipient=recipient_input)

            # 7. Verify Daily Transaction Limit
            sender_daily_spent = get_daily_spent(cursor, sender_acc_id)
            sender_daily_limit = Decimal(str(locked_sender['daily_limit']))
            if sender_daily_spent + amount > sender_daily_limit:
                conn.rollback()
                allowed = max(Decimal('0.00'), sender_daily_limit - sender_daily_spent)
                flash(f"Daily transaction limit exceeded! You have spent ₹{sender_daily_spent:,.2f} of your ₹{sender_daily_limit:,.2f} daily limit. Remaining allowance: ₹{allowed:,.2f}.", "danger")
                return render_template('wallet/transfer.html',
                                       account=locked_sender,
                                       daily_spent=sender_daily_spent,
                                       remaining_limit=allowed,
                                       recipient=recipient_input)

            # 8. Deduct from Sender
            cursor.execute(
                "UPDATE accounts SET balance = balance - %s WHERE id = %s",
                (amount, sender_acc_id)
            )

            # 9. Add to Receiver
            cursor.execute(
                "UPDATE accounts SET balance = balance + %s WHERE id = %s",
                (amount, receiver_acc_id)
            )

            # 10. Record Single-Entry Transfer in `transactions`
            txn_ref = str(uuid.uuid4())
            cursor.execute(
                """INSERT INTO transactions
                   (transaction_ref, from_account_id, to_account_id, transaction_type, amount, status, description)
                   VALUES (%s, %s, %s, 'transfer', %s, 'success', %s)""",
                (txn_ref, sender_acc_id, receiver_acc_id, amount, description)
            )

            # 11. Record Audit Log
            cursor.execute(
                """INSERT INTO audit_logs (user_id, action, details, ip_address)
                   VALUES (%s, 'TRANSFER', %s, %s)""",
                (user_id, f"Transferred ₹{amount:,.2f} from {locked_sender['account_number']} to {recipient['username']} ({locked_receiver['account_number']}). Ref: {txn_ref}", client_ip)
            )

            # 12. COMMIT THE ATOMIC TRANSACTION
            conn.commit()

            flash(f"Successfully transferred ₹{amount:,.2f} to {recipient['full_name']} (@{recipient['username']})! (Ref: {txn_ref[:8]}...)", "success")
            return redirect(url_for('wallet.dashboard'))

        except Exception as e:
            conn.rollback()
            flash("Transfer failed due to an unexpected system error. Your balance was not deducted.", "danger")
            return render_template('wallet/transfer.html',
                                   account=sender_account,
                                   daily_spent=daily_spent,
                                   remaining_limit=remaining_limit,
                                   recipient=recipient_input)
        finally:
            cursor.close()
            conn.close()

    cursor.close()
    conn.close()
    return render_template(
        'wallet/transfer.html',
        account=sender_account,
        daily_spent=daily_spent,
        remaining_limit=remaining_limit
    )


@wallet_bp.route('/history')
@login_required
def history():
    """
    Transaction History:
    - Lists all transactions involving the user's wallet (sent, received, deposited, withdrawn).
    - Supports filtering by type ('all', 'deposit', 'withdrawal', 'transfer').
    - Supports search by description, counterparty username, or transaction reference.
    - Formats counterparties dynamically.
    """
    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)

    cursor.execute("SELECT id, account_number, balance FROM accounts WHERE user_id = %s", (user_id,))
    account = cursor.fetchone()

    if not account:
        cursor.close()
        conn.close()
        flash("No wallet found.", "danger")
        return redirect(url_for('wallet.dashboard'))

    account_id = account['id']
    filter_type = request.args.get('type', 'all').lower()
    filter_status = request.args.get('status', 'all').lower()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    search_query = request.args.get('q', '').strip()

    try:
        # Base query joining counterparty users and accounts
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
            WHERE (t.from_account_id = %s OR t.to_account_id = %s)
        """
        params = [account_id, account_id]

        if filter_type in ['deposit', 'withdrawal', 'transfer']:
            sql += " AND t.transaction_type = %s"
            params.append(filter_type)

        if filter_status in ['success', 'failed']:
            sql += " AND t.status = %s"
            params.append(filter_status)

        if date_from:
            sql += " AND DATE(t.created_at) >= %s"
            params.append(date_from)

        if date_to:
            sql += " AND DATE(t.created_at) <= %s"
            params.append(date_to)

        if search_query:
            sql += """ AND (t.description LIKE %s OR t.transaction_ref LIKE %s
                            OR u_from.username LIKE %s OR u_to.username LIKE %s)"""
            wildcard = f"%{search_query}%"
            params.extend([wildcard, wildcard, wildcard, wildcard])

        sql += " ORDER BY t.created_at DESC"

        cursor.execute(sql, tuple(params))
        transactions = cursor.fetchall()

        return render_template(
            'wallet/history.html',
            account=account,
            transactions=transactions,
            filter_type=filter_type,
            filter_status=filter_status,
            date_from=date_from,
            date_to=date_to,
            search_query=search_query
        )

    except Exception as e:
        flash("An error occurred while loading transaction history.", "danger")
        return render_template('wallet/history.html', account=account, transactions=[], filter_type='all', search_query='')
    finally:
        cursor.close()
        conn.close()
