"""
test_auth.py — Automated verification script for Phase 3 Authentication

Tests all 7 required cases:
1. Successful registration (creates user + wallet account + audit log)
2. Duplicate registration (rejects existing username and email)
3. Successful login (authenticates hash, sets session, resets counter)
4. Wrong password (increments failed_logins counter)
5. Multiple failed logins (tracks consecutive attempts)
6. Account locking (locks account after 5 failed attempts, suspends wallet)
7. Successful logout (clears session, logs event)
"""

from app import app
from db import get_db_connection
from werkzeug.security import check_password_hash


def query_db(query, params=(), one=False):
    """Helper to query database with fresh connection."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(query, params)
    result = cursor.fetchone() if one else cursor.fetchall()
    cursor.close()
    conn.close()
    return result


def run_tests():
    print("=" * 60)
    print("  RUNNING SECUREPAY PHASE 3 AUTHENTICATION TESTS")
    print("=" * 60)

    client = app.test_client()

    # Clean up test user 'alice' if exists from previous runs
    existing_alice = query_db("SELECT id FROM users WHERE username = 'alice'", one=True)
    if existing_alice:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM audit_logs WHERE user_id = %s", (existing_alice['id'],))
        cursor.execute("DELETE FROM accounts WHERE user_id = %s", (existing_alice['id'],))
        cursor.execute("DELETE FROM users WHERE id = %s", (existing_alice['id'],))
        conn.commit()
        cursor.close()
        conn.close()

    # -------------------------------------------------------------
    # TEST 1: Successful Registration
    # -------------------------------------------------------------
    print("\n[TEST 1] Testing Successful Registration...")
    res = client.post('/register', data={
        'username': 'alice',
        'email': 'alice@example.com',
        'full_name': 'Alice Wonderland',
        'password': 'password123',
        'confirm_password': 'password123'
    }, follow_redirects=True)

    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    assert b"Registration successful" in res.data, "Flash message not found in response"

    # Verify Database state
    user = query_db("SELECT * FROM users WHERE username = 'alice'", one=True)
    assert user is not None, "User 'alice' was not created in database"
    assert user['email'] == 'alice@example.com'
    assert user['full_name'] == 'Alice Wonderland'
    assert user['is_locked'] == 0
    assert user['failed_logins'] == 0
    assert check_password_hash(user['password_hash'], 'password123'), "Password hash verification failed"
    assert not user['password_hash'].startswith('password123'), "Plaintext password stored!"

    # Verify Wallet Account creation
    account = query_db("SELECT * FROM accounts WHERE user_id = %s", (user['id'],), one=True)
    assert account is not None, "Wallet account was not created for user 'alice'"
    assert float(account['balance']) == 0.00
    assert account['status'] == 'active'

    # Verify Audit Log
    audit = query_db("SELECT * FROM audit_logs WHERE user_id = %s AND action = 'REGISTER'", (user['id'],), one=True)
    assert audit is not None, "Audit log for REGISTER not recorded"
    print("  --> PASS: User 'alice' created, wallet created, password hashed with Werkzeug, audit log saved.")

    # -------------------------------------------------------------
    # TEST 2: Duplicate Registration
    # -------------------------------------------------------------
    print("\n[TEST 2] Testing Duplicate Registration Rejection...")
    res_dup_username = client.post('/register', data={
        'username': 'alice',
        'email': 'different_email@example.com',
        'full_name': 'Another Alice',
        'password': 'password123',
        'confirm_password': 'password123'
    }, follow_redirects=True)
    assert b"Username is already taken" in res_dup_username.data, "Duplicate username check failed"

    res_dup_email = client.post('/register', data={
        'username': 'alice_new',
        'email': 'alice@example.com',
        'full_name': 'Another Alice',
        'password': 'password123',
        'confirm_password': 'password123'
    }, follow_redirects=True)
    assert b"An account with this email already exists" in res_dup_email.data, "Duplicate email check failed"
    print("  --> PASS: Duplicate username and email properly rejected.")

    # -------------------------------------------------------------
    # TEST 3: Successful Login
    # -------------------------------------------------------------
    print("\n[TEST 3] Testing Successful Login...")
    with client:
        res = client.post('/login', data={
            'username_or_email': 'alice',
            'password': 'password123'
        }, follow_redirects=True)
        assert res.status_code == 200
        assert b"Welcome back, Alice Wonderland" in res.data, "Welcome message not found"

        # Check session
        from flask import session
        assert session.get('user_id') == user['id'], "Session user_id not set"
        assert session.get('username') == 'alice', "Session username not set"

        # Check audit log
        login_audit = query_db("SELECT * FROM audit_logs WHERE user_id = %s AND action = 'LOGIN_SUCCESS'", (user['id'],), one=True)
        assert login_audit is not None, "LOGIN_SUCCESS audit log missing"
        print("  --> PASS: Login authenticated, session established, LOGIN_SUCCESS logged.")

    # -------------------------------------------------------------
    # TEST 4: Successful Logout
    # -------------------------------------------------------------
    print("\n[TEST 4] Testing Successful Logout...")
    with client:
        # Log in first
        client.post('/login', data={'username_or_email': 'alice', 'password': 'password123'})
        # Then log out
        res_logout = client.get('/logout', follow_redirects=True)
        assert b"logged out successfully" in res_logout.data
        assert 'user_id' not in session
        print("  --> PASS: Logout cleared session and redirected to login page.")

    # -------------------------------------------------------------
    # TEST 5: Wrong Password & Failed Login Tracking
    # -------------------------------------------------------------
    print("\n[TEST 5] Testing Wrong Password & Failed Login Counter...")
    res_wrong = client.post('/login', data={
        'username_or_email': 'alice',
        'password': 'wrongpassword'
    }, follow_redirects=True)
    assert b"Invalid credentials" in res_wrong.data
    assert b"4 attempt(s) remaining" in res_wrong.data

    state = query_db("SELECT failed_logins, is_locked FROM users WHERE id = %s", (user['id'],), one=True)
    assert state['failed_logins'] == 1
    assert state['is_locked'] == 0
    print("  --> PASS: Counter incremented to 1/5, warning message shown.")

    # -------------------------------------------------------------
    # TEST 6: Multiple Failed Logins & Account Locking
    # -------------------------------------------------------------
    print("\n[TEST 6] Testing Multiple Failed Logins & Account Locking...")
    for attempt in range(2, 6):
        res = client.post('/login', data={
            'username_or_email': 'alice',
            'password': 'wrongpassword'
        }, follow_redirects=True)

    locked_state = query_db("SELECT failed_logins, is_locked FROM users WHERE id = %s", (user['id'],), one=True)
    assert locked_state['failed_logins'] == 5, f"Expected 5 failed logins, got {locked_state['failed_logins']}"
    assert locked_state['is_locked'] == 1, "Account was not locked after 5 failed attempts"

    # Verify wallet status suspended
    acct_state = query_db("SELECT status FROM accounts WHERE user_id = %s", (user['id'],), one=True)
    assert acct_state['status'] == 'suspended', "Wallet status not suspended upon account lock"

    # Verify Subsequent Login is Blocked
    res_blocked = client.post('/login', data={
        'username_or_email': 'alice',
        'password': 'password123'  # Correct password but account is locked
    }, follow_redirects=True)
    assert b"Your account is locked" in res_blocked.data, "Locked account was not blocked"

    # Verify ACCOUNT_LOCKED in audit log
    lock_audit = query_db("SELECT * FROM audit_logs WHERE user_id = %s AND action = 'ACCOUNT_LOCKED'", (user['id'],), one=True)
    assert lock_audit is not None, "ACCOUNT_LOCKED audit log missing"
    print("  --> PASS: Account locked at 5 attempts, wallet suspended, subsequent logins blocked.")

    # -------------------------------------------------------------
    # TEST 7: Reset Failed-Login Count on Success (Test with user 'john')
    # -------------------------------------------------------------
    print("\n[TEST 7] Testing Failed-Login Count Reset on Success...")
    # John has 1 failed login first
    client.post('/login', data={'username_or_email': 'john', 'password': 'wrongpassword'})
    state_john = query_db("SELECT failed_logins FROM users WHERE username = 'john'", one=True)
    assert state_john['failed_logins'] == 1

    # John logs in with correct password
    client.post('/login', data={'username_or_email': 'john', 'password': 'password123'})
    state_john_reset = query_db("SELECT failed_logins FROM users WHERE username = 'john'", one=True)
    assert state_john_reset['failed_logins'] == 0
    print("  --> PASS: Failed logins counter reset to 0 upon successful login.")

    print("\n" + "=" * 60)
    print("  ALL 7 AUTHENTICATION TESTS PASSED PERFECTLY! [100%]")
    print("=" * 60)


if __name__ == '__main__':
    run_tests()
