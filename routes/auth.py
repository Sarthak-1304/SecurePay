"""
routes/auth.py — Authentication Routes (Register, Login, Logout)

SECURITY FEATURES IMPLEMENTED:
1. Werkzeug Password Hashing:
   - Uses generate_password_hash() (PBKDF2/scrypt with random salt).
   - Verifies with check_password_hash().
   - Plaintext passwords never touch the database or logs.

2. Brute-Force Protection / Account Locking:
   - Tracks consecutive failed logins in `users.failed_logins`.
   - Automatically locks account (is_locked=TRUE) after 5 failed attempts.
   - Resets failed_logins counter to 0 on successful authentication.

3. Atomic Account Creation:
   - User profile + wallet account are created in a SINGLE SQL transaction.
   - Both succeed or both roll back (no orphan users without wallets).

4. Audit Logging:
   - Every registration, login success, login failure, and account lock
     is recorded in the `audit_logs` table with IP address and timestamp.
"""

from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from db import get_db_connection
from helpers.validators import validate_registration

auth_bp = Blueprint('auth', __name__)

# Maximum allowed failed login attempts before locking account
MAX_FAILED_ATTEMPTS = 5


def get_client_ip():
    """Extract client IP address safely from request headers or remote_addr."""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    return request.remote_addr or '127.0.0.1'


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """
    User Registration:
    - Validates inputs (username format, email format, password length, match).
    - Checks for existing username or email duplicates.
    - Hashes password using Werkzeug.
    - Creates user + initial wallet account inside one atomic transaction.
    """
    if 'user_id' in session:
        return redirect(url_for('home'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        full_name = request.form.get('full_name', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        # 1. Server-side input validation
        is_valid, error_message = validate_registration(
            username, email, full_name, password, confirm_password
        )
        if not is_valid:
            flash(error_message, "danger")
            return render_template('auth/register.html',
                                   username=username, email=email, full_name=full_name)

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            # 2. Check for duplicate username or email
            cursor.execute(
                "SELECT id, username, email FROM users WHERE username = %s OR email = %s",
                (username, email)
            )
            existing_user = cursor.fetchone()

            if existing_user:
                if existing_user['username'].lower() == username.lower():
                    flash("Username is already taken. Please choose another.", "danger")
                else:
                    flash("An account with this email already exists.", "danger")
                return render_template('auth/register.html',
                                       username=username, email=email, full_name=full_name)

            # 3. Hash password securely
            password_hash = generate_password_hash(password)

            # 4. Insert user record
            cursor.execute(
                """INSERT INTO users (username, email, password_hash, full_name, role)
                   VALUES (%s, %s, %s, %s, 'user')""",
                (username, email, password_hash, full_name)
            )
            new_user_id = cursor.lastrowid

            # 5. Create associated wallet account (ACC00001, ACC00002, ...)
            account_number = f"ACC{new_user_id:05d}"
            cursor.execute(
                """INSERT INTO accounts (user_id, account_number, balance, status)
                   VALUES (%s, %s, 0.00, 'active')""",
                (new_user_id, account_number)
            )

            # 6. Audit log entry
            client_ip = get_client_ip()
            cursor.execute(
                """INSERT INTO audit_logs (user_id, action, details, ip_address)
                   VALUES (%s, 'REGISTER', %s, %s)""",
                (new_user_id, f"Registered new user '{username}' with wallet '{account_number}'", client_ip)
            )

            # Commit the entire transaction atomically
            conn.commit()

            flash(f"Registration successful! Your wallet account ({account_number}) is ready. Please log in.", "success")
            return redirect(url_for('auth.login'))

        except Exception as e:
            conn.rollback()
            flash(f"An unexpected error occurred during registration. Please try again.", "danger")
            return render_template('auth/register.html',
                                   username=username, email=email, full_name=full_name)
        finally:
            cursor.close()
            conn.close()

    return render_template('auth/register.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """
    User Login:
    - Authenticates username or email with password hash.
    - Prevents login if account is locked.
    - Increments failed_logins on wrong password and locks at 5 failed attempts.
    - Resets failed_logins to 0 on successful authentication.
    - Sets secure server-side session.
    """
    if 'user_id' in session:
        return redirect(url_for('home'))

    if request.method == 'POST':
        login_identifier = request.form.get('username_or_email', '').strip()
        password = request.form.get('password', '')
        client_ip = get_client_ip()

        if not login_identifier or not password:
            flash("Please enter both username/email and password.", "danger")
            return render_template('auth/login.html', username_or_email=login_identifier)

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            # Query user by username or email using parameterized query
            cursor.execute(
                """SELECT id, username, email, password_hash, full_name, role, is_locked, failed_logins
                   FROM users
                   WHERE username = %s OR email = %s""",
                (login_identifier, login_identifier.lower())
            )
            user = cursor.fetchone()

            # Case 1: User does not exist
            if not user:
                # Log failed attempt anonymously to audit_logs
                cursor.execute(
                    """INSERT INTO audit_logs (user_id, action, details, ip_address)
                       VALUES (NULL, 'LOGIN_FAILED', %s, %s)""",
                    (f"Login failed: User '{login_identifier}' not found", client_ip)
                )
                conn.commit()
                # Use generic error message to prevent user enumeration
                flash("Invalid username/email or password.", "danger")
                return render_template('auth/login.html', username_or_email=login_identifier)

            user_id = user['id']

            # Case 2: Account is locked
            if user['is_locked']:
                cursor.execute(
                    """INSERT INTO audit_logs (user_id, action, details, ip_address)
                       VALUES (%s, 'LOGIN_BLOCKED', 'Login attempt on locked account', %s)""",
                    (user_id, client_ip)
                )
                conn.commit()
                flash("Your account is locked due to repeated failed login attempts. Please contact an administrator.", "danger")
                return render_template('auth/login.html', username_or_email=login_identifier)

            # Case 3: Verify password hash
            if not check_password_hash(user['password_hash'], password):
                new_failed = user['failed_logins'] + 1

                if new_failed >= MAX_FAILED_ATTEMPTS:
                    # Lock account and suspend wallet
                    cursor.execute(
                        "UPDATE users SET failed_logins = %s, is_locked = TRUE WHERE id = %s",
                        (new_failed, user_id)
                    )
                    cursor.execute(
                        "UPDATE accounts SET status = 'suspended' WHERE user_id = %s",
                        (user_id,)
                    )
                    cursor.execute(
                        """INSERT INTO audit_logs (user_id, action, details, ip_address)
                           VALUES (%s, 'ACCOUNT_LOCKED', %s, %s)""",
                        (user_id, f"Account locked after {new_failed} consecutive failed login attempts", client_ip)
                    )
                    conn.commit()
                    flash(f"Account locked! You exceeded {MAX_FAILED_ATTEMPTS} failed attempts. Contact an admin to unlock.", "danger")
                else:
                    # Increment failed attempts counter
                    cursor.execute(
                        "UPDATE users SET failed_logins = %s WHERE id = %s",
                        (new_failed, user_id)
                    )
                    cursor.execute(
                        """INSERT INTO audit_logs (user_id, action, details, ip_address)
                           VALUES (%s, 'LOGIN_FAILED', %s, %s)""",
                        (user_id, f"Wrong password attempt {new_failed} of {MAX_FAILED_ATTEMPTS}", client_ip)
                    )
                    conn.commit()
                    remaining = MAX_FAILED_ATTEMPTS - new_failed
                    flash(f"Invalid credentials. You have {remaining} attempt(s) remaining before your account is locked.", "warning")

                return render_template('auth/login.html', username_or_email=login_identifier)

            # Case 4: Successful Login
            # Reset failed login counter to 0
            if user['failed_logins'] > 0:
                cursor.execute(
                    "UPDATE users SET failed_logins = 0 WHERE id = %s",
                    (user_id,)
                )

            cursor.execute(
                """INSERT INTO audit_logs (user_id, action, details, ip_address)
                   VALUES (%s, 'LOGIN_SUCCESS', 'User logged in successfully', %s)""",
                (user_id, client_ip)
            )
            conn.commit()

            # Set session variables
            session.clear()
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['full_name'] = user['full_name']
            session['role'] = user['role']

            flash(f"Welcome back, {user['full_name']}!", "success")

            next_page = request.args.get('next')
            if next_page and next_page.startswith('/'):
                return redirect(next_page)

            # Direct admin to Admin Control Panel; regular user to Wallet Dashboard
            if user['role'] == 'admin':
                return redirect(url_for('admin.dashboard'))
            return redirect(url_for('wallet.dashboard'))

        except Exception as e:
            conn.rollback()
            flash("An error occurred during login. Please try again.", "danger")
            return render_template('auth/login.html', username_or_email=login_identifier)
        finally:
            cursor.close()
            conn.close()

    return render_template('auth/login.html')


@auth_bp.route('/logout')
def logout():
    """
    User Logout:
    - Logs the logout event in audit_logs.
    - Clears the session dictionary.
    - Redirects to login page with a success message.
    """
    user_id = session.get('user_id')
    client_ip = get_client_ip()

    if user_id:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO audit_logs (user_id, action, details, ip_address)
                   VALUES (%s, 'LOGOUT', 'User logged out', %s)""",
                (user_id, client_ip)
            )
            conn.commit()
            cursor.close()
            conn.close()
        except Exception:
            pass  # Session cleanup must succeed even if audit log fails

    session.clear()
    flash("You have been logged out successfully.", "info")
    return redirect(url_for('auth.login'))


@auth_bp.route('/request-unlock', methods=['GET', 'POST'])
def request_unlock():
    """
    Account Unlock Request Form:
    - Allows locked users to submit an unlock appeal to system administrators.
    - Records an UNLOCK_REQUEST event in `audit_logs` so admins can review and unlock.
    """
    if request.method == 'POST':
        identifier = request.form.get('username_or_email', '').strip()
        reason = request.form.get('reason', '').strip()[:255] or "User requested unlock via support form."
        client_ip = get_client_ip()

        if not identifier:
            flash("Please provide your username or email address.", "danger")
            return render_template('auth/request_unlock.html')

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                "SELECT id, username, email, is_locked FROM users WHERE username = %s OR email = %s",
                (identifier, identifier.lower())
            )
            user = cursor.fetchone()

            if user:
                # Log unlock request in audit_logs so admin sees it
                cursor.execute(
                    """INSERT INTO audit_logs (user_id, action, details, ip_address)
                       VALUES (%s, 'UNLOCK_REQUEST', %s, %s)""",
                    (user['id'], f"Unlock Request from @{user['username']}: {reason}", client_ip)
                )
                conn.commit()

            # Show friendly message regardless of existence (prevents user enumeration)
            flash("Your unlock request has been submitted to the administrator queue. Please check back shortly.", "success")
            return redirect(url_for('auth.login'))
        except Exception as e:
            conn.rollback()
            flash("An error occurred while submitting your request. Please try again later.", "danger")
            return render_template('auth/request_unlock.html')
        finally:
            cursor.close()
            conn.close()

    return render_template('auth/request_unlock.html')
