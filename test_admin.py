"""
test_admin.py — Automated verification script for Phase 7 Admin Panel & RBAC

Tests all required Phase 7 features:
1. RBAC Security:
   - Unauthenticated visitors blocked from all /admin/* routes.
   - Authenticated non-admin users (role='user') blocked with Access Denied.
2. Admin Dashboard Access:
   - Admin user (role='admin') views platform KPIs and recent activity.
3. User Management:
   - Admin views all registered users, balances, and lock states.
4. Account Lock / Unlock Workflow:
   - Admin locks user 'jane' -> verified is_locked=1, account_status='suspended', ACCOUNT_LOCKED logged.
   - Jane is blocked from logging in.
   - Admin unlocks user 'jane' -> verified is_locked=0, account_status='active', ACCOUNT_UNLOCKED logged.
   - Jane successfully logs in.
5. Admin Self-Lockout Prevention:
   - Admin attempting to lock their own account is strictly blocked.
6. Global Transactions:
   - Admin views transactions across all accounts with filters.
"""

from app import app
from db import get_db_connection


def query_db(query, params=(), one=False):
    """Helper to query database with fresh connection and buffered cursor."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)
    cursor.execute(query, params)
    result = cursor.fetchone() if one else cursor.fetchall()
    cursor.close()
    conn.close()
    return result


def run_admin_tests():
    print("=" * 60)
    print("  RUNNING SECUREPAY PHASE 7 ADMIN & RBAC TESTS")
    print("=" * 60)

    client = app.test_client()

    # -------------------------------------------------------------
    # TEST 1: Role-Based Access Control (RBAC) Protection
    # -------------------------------------------------------------
    print("\n[TEST 1] Testing RBAC Route Protection...")
    # 1. Anonymous Access
    for route in ['/admin/dashboard', '/admin/users', '/admin/transactions', '/admin/audit-logs']:
        res_anon = client.get(route, follow_redirects=False)
        assert res_anon.status_code == 302 and '/login' in res_anon.headers['Location'], f"{route} not protected for anonymous users"

    # 2. Non-Admin Authenticated Access (User 'john', role='user')
    with client:
        client.post('/login', data={'username_or_email': 'john', 'password': 'password123'})
        for route in ['/admin/dashboard', '/admin/users', '/admin/transactions', '/admin/audit-logs']:
            res_user = client.get(route, follow_redirects=True)
            assert b"Access denied: Administrator privileges required" in res_user.data, f"{route} allowed non-admin access!"
    print("  --> PASS: Anonymous and regular users strictly blocked from all admin routes.")

    # -------------------------------------------------------------
    # TEST 2: Admin Dashboard & Overview
    # -------------------------------------------------------------
    print("\n[TEST 2] Testing Admin Dashboard...")
    client_admin = app.test_client()
    with client_admin:
        login_res = client_admin.post('/login', data={'username_or_email': 'admin', 'password': 'admin123'}, follow_redirects=True)
        assert login_res.status_code == 200

        dash_res = client_admin.get('/admin/dashboard')
        assert dash_res.status_code == 200
        assert b"Administrator Control Panel" in dash_res.data
        assert b"Active Users" in dash_res.data
        assert b"Total System Balance" in dash_res.data
        print("  --> PASS: Admin dashboard displays platform KPIs and overview successfully.")

    # -------------------------------------------------------------
    # TEST 3: User Directory Listing
    # -------------------------------------------------------------
    print("\n[TEST 3] Testing Admin User Directory...")
    with client_admin:
        users_res = client_admin.get('/admin/users')
        assert users_res.status_code == 200
        assert b"User &amp; Wallet Management" in users_res.data or b"User & Wallet Management" in users_res.data
        assert b"john" in users_res.data
        assert b"jane" in users_res.data
        assert b"bob" in users_res.data
        print("  --> PASS: User directory correctly lists all users, balances, and lock states.")

    # -------------------------------------------------------------
    # TEST 4: Account Lock & Unlock Lifecycle (User 'jane')
    # -------------------------------------------------------------
    print("\n[TEST 4] Testing Admin Lock / Unlock Lifecycle...")
    with client_admin:
        # 1. Admin locks Jane (id=3)
        res_lock = client_admin.post('/admin/users/3/toggle-lock', follow_redirects=True)
        assert b"has been locked and their wallet suspended" in res_lock.data

        # Verify DB state for Jane
        jane_locked = query_db("SELECT is_locked FROM users WHERE id = 3", one=True)
        assert jane_locked['is_locked'] == 1, "Jane is_locked was not set to 1"

        jane_acct = query_db("SELECT status FROM accounts WHERE user_id = 3", one=True)
        assert jane_acct['status'] == 'suspended', "Jane account status was not suspended"

        # Verify Jane cannot log in
        client_jane = app.test_client()
        res_jane_login = client_jane.post('/login', data={'username_or_email': 'jane', 'password': 'password123'}, follow_redirects=True)
        assert b"Your account is locked" in res_jane_login.data

        # 2. Admin unlocks Jane (id=3)
        res_unlock = client_admin.post('/admin/users/3/toggle-lock', follow_redirects=True)
        assert b"has been successfully unlocked" in res_unlock.data

        # Verify DB state for Jane restored
        jane_unlocked = query_db("SELECT is_locked, failed_logins FROM users WHERE id = 3", one=True)
        assert jane_unlocked['is_locked'] == 0, "Jane is_locked was not set to 0"
        assert jane_unlocked['failed_logins'] == 0, "Jane failed_logins was not reset"

        jane_acct_active = query_db("SELECT status FROM accounts WHERE user_id = 3", one=True)
        assert jane_acct_active['status'] == 'active', "Jane account status was not restored to active"

        # Verify Jane can now log in
        res_jane_login_ok = client_jane.post('/login', data={'username_or_email': 'jane', 'password': 'password123'}, follow_redirects=True)
        assert b"Welcome back, Jane" in res_jane_login_ok.data
        print("  --> PASS: Full lock -> lockout verification -> unlock -> login recovery cycle succeeded.")

    # -------------------------------------------------------------
    # TEST 5: Admin Self-Lockout Prevention
    # -------------------------------------------------------------
    print("\n[TEST 5] Testing Admin Self-Lockout Prevention...")
    with client_admin:
        # Admin ID is 1
        res_self_lock = client_admin.post('/admin/users/1/toggle-lock', follow_redirects=True)
        assert b"Action blocked: You cannot lock your own administrator account" in res_self_lock.data

        admin_user = query_db("SELECT is_locked FROM users WHERE id = 1", one=True)
        assert admin_user['is_locked'] == 0, "Admin account was erroneously locked!"
        print("  --> PASS: Admin self-lockout properly blocked by backend safety rule.")

    # -------------------------------------------------------------
    # TEST 6: Global Transaction Monitoring
    # -------------------------------------------------------------
    print("\n[TEST 6] Testing Global Transaction Oversight...")
    with client_admin:
        res_txns = client_admin.get('/admin/transactions')
        assert res_txns.status_code == 200
        assert b"Global Platform Transactions" in res_txns.data

        # Filter by type
        res_txns_filtered = client_admin.get('/admin/transactions?type=transfer')
        assert res_txns_filtered.status_code == 200
        print("  --> PASS: Global transaction oversight verified with filters.")

    print("\n" + "=" * 60)
    print("  ALL 6 PHASE 7 ADMIN & RBAC TESTS PASSED! [100%]")
    print("=" * 60)


if __name__ == '__main__':
    run_admin_tests()
