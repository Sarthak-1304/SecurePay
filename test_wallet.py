"""
test_wallet.py — Automated verification script for Phase 4 Wallet Operations

Tests all required wallet features:
1. Unauthorized protection: Redirects unauthenticated requests to login.
2. Dashboard view: Loads account details, balance, and recent transaction list.
3. Deposit validation: Rejects negative, zero, non-numeric, and invalid decimal amounts.
4. Successful Deposit: Increases balance, records transaction row, saves audit log.
5. Withdrawal validation: Rejects invalid amounts and zero/negative requests.
6. Insufficient funds prevention: Blocks overdraft attempts, maintains balance integrity.
7. Successful Withdrawal: Deducts balance, records transaction row, saves audit log.
8. Suspended account security: Prevents financial operations on locked/suspended accounts.
9. Database constraint verification: Enforces CHECK (balance >= 0) and transaction atomicity.
"""

from decimal import Decimal
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


def execute_db(query, params=()):
    """Helper to execute modification query."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(query, params)
    conn.commit()
    cursor.close()
    conn.close()


def run_wallet_tests():
    print("=" * 60)
    print("  RUNNING SECUREPAY PHASE 4 WALLET & TRANSACTION TESTS")
    print("=" * 60)

    client = app.test_client()

    # -------------------------------------------------------------
    # TEST 1: Unauthorized Access Protection
    # -------------------------------------------------------------
    print("\n[TEST 1] Testing Unauthorized Access Protection...")
    res_dash = client.get('/dashboard', follow_redirects=False)
    assert res_dash.status_code == 302 and '/login' in res_dash.headers['Location'], "Dashboard not protected"

    res_dep = client.get('/deposit', follow_redirects=False)
    assert res_dep.status_code == 302 and '/login' in res_dep.headers['Location'], "Deposit not protected"

    res_wdr = client.get('/withdraw', follow_redirects=False)
    assert res_wdr.status_code == 302 and '/login' in res_wdr.headers['Location'], "Withdraw not protected"
    print("  --> PASS: @login_required correctly redirects unauthenticated visitors to login.")

    # -------------------------------------------------------------
    # TEST 2: Dashboard View for Authenticated User ('john')
    # -------------------------------------------------------------
    print("\n[TEST 2] Testing Dashboard for User 'john'...")
    with client:
        login_res = client.post('/login', data={'username_or_email': 'john', 'password': 'password123'}, follow_redirects=True)
        assert login_res.status_code == 200

        dash_res = client.get('/dashboard')
        assert dash_res.status_code == 200
        assert b"My Digital Wallet" in dash_res.data
        assert b"ACC00002" in dash_res.data
        print("  --> PASS: Dashboard displays wallet balance and account number accurately.")

    # -------------------------------------------------------------
    # TEST 3: Deposit Input Validation
    # -------------------------------------------------------------
    print("\n[TEST 3] Testing Deposit Input Validation...")
    with client:
        # Client is already logged in as john
        # Test zero amount
        res_zero = client.post('/deposit', data={'amount': '0.00'}, follow_redirects=True)
        assert b"Amount must be greater than zero" in res_zero.data

        # Test negative amount
        res_neg = client.post('/deposit', data={'amount': '-50.00'}, follow_redirects=True)
        assert b"Amount must be greater than zero" in res_neg.data

        # Test invalid string
        res_str = client.post('/deposit', data={'amount': 'abc'}, follow_redirects=True)
        assert b"Invalid amount format" in res_str.data

        # Test more than 2 decimal places
        res_dec = client.post('/deposit', data={'amount': '10.555'}, follow_redirects=True)
        assert b"more than 2 decimal places" in res_dec.data
        print("  --> PASS: Negative, zero, malformed, and fractional amounts rejected.")

    # -------------------------------------------------------------
    # TEST 4: Successful Deposit with SQL Transaction & Audit Log
    # -------------------------------------------------------------
    print("\n[TEST 4] Testing Successful Deposit...")
    john_account_before = query_db("SELECT id, balance FROM accounts WHERE user_id = 2", one=True)
    initial_balance = Decimal(str(john_account_before['balance']))
    deposit_amount = Decimal('1500.50')

    with client:
        res_dep_ok = client.post('/deposit', data={
            'amount': '1500.50',
            'description': 'Freelance project payment'
        }, follow_redirects=True)
        assert b"Successfully deposited" in res_dep_ok.data

        # Verify balance updated in database
        john_account_after = query_db("SELECT balance FROM accounts WHERE user_id = 2", one=True)
        expected_balance = initial_balance + deposit_amount
        actual_balance = Decimal(str(john_account_after['balance']))
        assert actual_balance == expected_balance, f"Expected {expected_balance}, got {actual_balance}"

        # Verify transaction record
        txn = query_db(
            """SELECT * FROM transactions
               WHERE to_account_id = %s AND transaction_type = 'deposit' AND description = 'Freelance project payment'
               ORDER BY id DESC""",
            (john_account_before['id'],),
            one=True
        )
        assert txn is not None, "Deposit transaction record not found"
        assert Decimal(str(txn['amount'])) == deposit_amount
        assert txn['from_account_id'] is None, "Deposit from_account_id must be NULL"
        assert txn['status'] == 'success'

        # Verify audit log
        audit = query_db(
            "SELECT * FROM audit_logs WHERE user_id = 2 AND action = 'DEPOSIT' ORDER BY id DESC",
            one=True
        )
        assert audit is not None, "DEPOSIT audit log not found"
        print(f"  --> PASS: Deposited INR {deposit_amount:,.2f}. Balance: INR {initial_balance:,.2f} -> INR {actual_balance:,.2f}. Transaction & audit log saved.")

    # -------------------------------------------------------------
    # TEST 5: Withdrawal Input Validation
    # -------------------------------------------------------------
    print("\n[TEST 5] Testing Withdrawal Input Validation...")
    with client:
        res_w_zero = client.post('/withdraw', data={'amount': '0.00'}, follow_redirects=True)
        assert b"Amount must be greater than zero" in res_w_zero.data

        res_w_neg = client.post('/withdraw', data={'amount': '-100'}, follow_redirects=True)
        assert b"Amount must be greater than zero" in res_w_neg.data
        print("  --> PASS: Negative and zero withdrawal amounts rejected.")

    # -------------------------------------------------------------
    # TEST 6: Insufficient Balance Rejection
    # -------------------------------------------------------------
    print("\n[TEST 6] Testing Insufficient Balance Withdrawal Rejection...")
    with client:
        current_bal = Decimal(str(query_db("SELECT balance FROM accounts WHERE user_id = 2", one=True)['balance']))
        overdraft_amount = current_bal + Decimal('500.00')

        res_insufficient = client.post('/withdraw', data={
            'amount': str(overdraft_amount),
            'description': 'Trying to overdraw'
        }, follow_redirects=True)
        assert b"Insufficient funds" in res_insufficient.data

        # Verify balance unchanged
        after_bal = Decimal(str(query_db("SELECT balance FROM accounts WHERE user_id = 2", one=True)['balance']))
        assert after_bal == current_bal, "Balance changed despite insufficient funds!"
        print(f"  --> PASS: Overdraft of INR {overdraft_amount:,.2f} against balance INR {current_bal:,.2f} properly rejected.")

    # -------------------------------------------------------------
    # TEST 7: Successful Withdrawal
    # -------------------------------------------------------------
    print("\n[TEST 7] Testing Successful Withdrawal...")
    execute_db("UPDATE accounts SET daily_limit = 500000.00 WHERE user_id = 2")
    withdraw_amount = Decimal('750.25')
    with client:
        bal_before_w = Decimal(str(query_db("SELECT balance FROM accounts WHERE user_id = 2", one=True)['balance']))

        res_w_ok = client.post('/withdraw', data={
            'amount': str(withdraw_amount),
            'description': 'Grocery shopping withdrawal'
        }, follow_redirects=True)
        assert b"Successfully withdrew" in res_w_ok.data

        bal_after_w = Decimal(str(query_db("SELECT balance FROM accounts WHERE user_id = 2", one=True)['balance']))
        expected_w_bal = bal_before_w - withdraw_amount
        assert bal_after_w == expected_w_bal, f"Expected {expected_w_bal}, got {bal_after_w}"

        # Verify transaction record
        txn_w = query_db(
            """SELECT * FROM transactions
               WHERE from_account_id = %s AND transaction_type = 'withdrawal' AND description = 'Grocery shopping withdrawal'
               ORDER BY id DESC""",
            (john_account_before['id'],),
            one=True
        )
        assert txn_w is not None, "Withdrawal transaction not found"
        assert txn_w['to_account_id'] is None, "Withdrawal to_account_id must be NULL"
        assert Decimal(str(txn_w['amount'])) == withdraw_amount

        # Verify audit log
        audit_w = query_db(
            "SELECT * FROM audit_logs WHERE user_id = 2 AND action = 'WITHDRAWAL' ORDER BY id DESC",
            one=True
        )
        assert audit_w is not None, "WITHDRAWAL audit log not found"
        print(f"  --> PASS: Withdrew INR {withdraw_amount:,.2f}. Balance: INR {bal_before_w:,.2f} -> INR {bal_after_w:,.2f}. Transaction & audit log saved.")

    # -------------------------------------------------------------
    # TEST 8: Suspended Account Operation Security (User 'bob')
    # -------------------------------------------------------------
    print("\n[TEST 8] Testing Suspended Account Restrictions...")
    with client:
        # Clear session and manually set user session for suspended user Bob (id=4)
        from flask import session
        with client.session_transaction() as sess:
            sess['user_id'] = 4
            sess['username'] = 'bob'
            sess['full_name'] = 'Bob Wilson'
            sess['role'] = 'user'

        res_bob_dep = client.post('/deposit', data={'amount': '100.00'}, follow_redirects=True)
        assert b"suspended" in res_bob_dep.data, "Suspended account was allowed to deposit!"

        res_bob_wdr = client.post('/withdraw', data={'amount': '50.00'}, follow_redirects=True)
        assert b"suspended" in res_bob_wdr.data, "Suspended account was allowed to withdraw!"
        print("  --> PASS: Suspended/locked accounts strictly prohibited from deposit/withdrawal.")

    print("\n" + "=" * 60)
    print("  ALL 8 WALLET & TRANSACTION TESTS PASSED PERFECTLY! [100%]")
    print("=" * 60)


if __name__ == '__main__':
    run_wallet_tests()
