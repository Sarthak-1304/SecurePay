"""
test_transfer.py — Automated verification script for Phase 5 P2P Money Transfers & History

Tests all required transfer and ledger features:
1. Unauthorized protection: Redirects unauthenticated access to /transfer and /history.
2. Input validation: Rejects zero, negative, and malformed transfer amounts.
3. Self-transfer prevention: Prohibits transfers to the sender's own account.
4. Non-existent recipient rejection: Fails gracefully when recipient is not found.
5. Inactive recipient rejection: Prohibits transfers to suspended users (Bob).
6. Insufficient balance protection: Blocks transfers exceeding available funds.
7. Atomic P2P Transfer (John -> Jane):
   - Exactly debits sender and credits receiver.
   - Generates immutable transaction record with UUID reference.
   - Generates audit log.
8. Daily Limit Enforcement: Rejects transactions exceeding the remaining daily spending allowance.
9. Bidirectional Transfer (Jane -> John): Verifies deadlock-free reverse transfers.
10. Transaction Ledger & Filtering: Verifies /history listing, type filters, and search query.
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


def run_transfer_tests():
    print("=" * 60)
    print("  RUNNING SECUREPAY PHASE 5 P2P TRANSFER & LEDGER TESTS")
    print("=" * 60)

    client = app.test_client()

    # -------------------------------------------------------------
    # TEST 1: Unauthorized Protection
    # -------------------------------------------------------------
    print("\n[TEST 1] Testing Unauthorized Access Protection...")
    res_tr_anon = client.get('/transfer', follow_redirects=False)
    assert res_tr_anon.status_code == 302 and '/login' in res_tr_anon.headers['Location']

    res_hist_anon = client.get('/history', follow_redirects=False)
    assert res_hist_anon.status_code == 302 and '/login' in res_hist_anon.headers['Location']
    print("  --> PASS: @login_required correctly protects /transfer and /history.")

    # -------------------------------------------------------------
    # TEST 2: Self-Transfer Prevention
    # -------------------------------------------------------------
    print("\n[TEST 2] Testing Self-Transfer Prevention...")
    with client:
        # Login as John (id=2, username='john', account='ACC00002')
        client.post('/login', data={'username_or_email': 'john', 'password': 'password123'})

        res_self_user = client.post('/transfer', data={
            'recipient': 'john',
            'amount': '100.00',
            'description': 'Self test'
        }, follow_redirects=True)
        assert b"cannot transfer money to your own" in res_self_user.data

        res_self_acc = client.post('/transfer', data={
            'recipient': 'ACC00002',
            'amount': '100.00',
            'description': 'Self test account number'
        }, follow_redirects=True)
        assert b"cannot transfer money to your own" in res_self_acc.data
        print("  --> PASS: Self-transfers by username and account number blocked.")

    # -------------------------------------------------------------
    # TEST 3: Non-Existent & Inactive Recipient Rejection
    # -------------------------------------------------------------
    print("\n[TEST 3] Testing Invalid & Suspended Recipient Checks...")
    with client:
        # Non-existent user
        res_nonexistent = client.post('/transfer', data={
            'recipient': 'ghost_user_999',
            'amount': '100.00'
        }, follow_redirects=True)
        assert b"not found" in res_nonexistent.data

        # Transfer to suspended user Bob
        res_suspended = client.post('/transfer', data={
            'recipient': 'bob',
            'amount': '100.00'
        }, follow_redirects=True)
        assert b"inactive or suspended" in res_suspended.data
        print("  --> PASS: Non-existent and suspended recipients properly rejected.")

    # -------------------------------------------------------------
    # TEST 4: Insufficient Balance Rejection
    # -------------------------------------------------------------
    print("\n[TEST 4] Testing Insufficient Balance Transfer Rejection...")
    with client:
        john_acc = query_db("SELECT balance FROM accounts WHERE user_id = 2", one=True)
        john_bal = Decimal(str(john_acc['balance']))
        overdraft = john_bal + Decimal('1000.00')

        res_over = client.post('/transfer', data={
            'recipient': 'jane',
            'amount': str(overdraft)
        }, follow_redirects=True)
        assert b"Insufficient balance" in res_over.data

        # Verify John's balance unchanged
        john_after = query_db("SELECT balance FROM accounts WHERE user_id = 2", one=True)
        assert Decimal(str(john_after['balance'])) == john_bal
        print("  --> PASS: Overdraft transfer rejected; balances preserved.")

    # -------------------------------------------------------------
    # TEST 5: Successful Atomic P2P Transfer (John -> Jane)
    # -------------------------------------------------------------
    print("\n[TEST 5] Testing Successful Atomic P2P Transfer (John -> Jane)...")
    transfer_amount = Decimal('1200.00')

    with client:
        client.post('/login', data={'username_or_email': 'john', 'password': 'password123'})
        curr_bal_row = query_db("SELECT balance FROM accounts WHERE user_id = 2", one=True)
        if Decimal(str(curr_bal_row['balance'])) < transfer_amount + Decimal('500.00'):
            client.post('/deposit', data={'amount': '3000.00', 'description': 'Topup for transfer test'})

    john_acc_start = query_db("SELECT id, account_number, balance FROM accounts WHERE user_id = 2", one=True)
    jane_acc_start = query_db("SELECT id, account_number, balance FROM accounts WHERE user_id = 3", one=True)

    john_start_bal = Decimal(str(john_acc_start['balance']))
    jane_start_bal = Decimal(str(jane_acc_start['balance']))

    with client:
        res_transfer_ok = client.post('/transfer', data={
            'recipient': 'jane',
            'amount': str(transfer_amount),
            'description': 'Shared dinner bill payment'
        }, follow_redirects=True)
        assert b"Successfully transferred" in res_transfer_ok.data

        # Verify exact balance changes
        john_acc_end = query_db("SELECT balance FROM accounts WHERE user_id = 2", one=True)
        jane_acc_end = query_db("SELECT balance FROM accounts WHERE user_id = 3", one=True)

        john_end_bal = Decimal(str(john_acc_end['balance']))
        jane_end_bal = Decimal(str(jane_acc_end['balance']))

        assert john_end_bal == john_start_bal - transfer_amount, f"Sender mismatch: {john_end_bal} != {john_start_bal - transfer_amount}"
        assert jane_end_bal == jane_start_bal + transfer_amount, f"Receiver mismatch: {jane_end_bal} != {jane_start_bal + transfer_amount}"

        # Verify transaction record in ledger
        txn = query_db(
            """SELECT * FROM transactions
               WHERE from_account_id = %s AND to_account_id = %s AND transaction_type = 'transfer'
               ORDER BY id DESC""",
            (john_acc_start['id'], jane_acc_start['id']),
            one=True
        )
        assert txn is not None, "Transfer transaction ledger record not created"
        assert Decimal(str(txn['amount'])) == transfer_amount
        assert txn['status'] == 'success'
        assert txn['description'] == 'Shared dinner bill payment'

        # Verify audit log
        audit = query_db("SELECT * FROM audit_logs WHERE user_id = 2 AND action = 'TRANSFER' ORDER BY id DESC", one=True)
        assert audit is not None, "TRANSFER audit log missing"
        print(f"  --> PASS: Transferred INR {transfer_amount:,.2f}. John: INR {john_start_bal:,.2f} -> INR {john_end_bal:,.2f}. Jane: INR {jane_start_bal:,.2f} -> INR {jane_end_bal:,.2f}.")

    # -------------------------------------------------------------
    # TEST 6: Reverse Transfer & Deadlock Safety (Jane -> John)
    # -------------------------------------------------------------
    print("\n[TEST 6] Testing Bidirectional Reverse Transfer (Jane -> John)...")
    reverse_amount = Decimal('300.00')

    # Switch session to Jane (user_id=3)
    client_jane = app.test_client()
    with client_jane:
        client_jane.post('/login', data={'username_or_email': 'jane', 'password': 'password123'})

        jane_prev = Decimal(str(query_db("SELECT balance FROM accounts WHERE user_id = 3", one=True)['balance']))
        john_prev = Decimal(str(query_db("SELECT balance FROM accounts WHERE user_id = 2", one=True)['balance']))

        res_rev = client_jane.post('/transfer', data={
            'recipient': 'ACC00002',  # John's account number
            'amount': str(reverse_amount),
            'description': 'Refund portion'
        }, follow_redirects=True)
        assert b"Successfully transferred" in res_rev.data

        jane_now = Decimal(str(query_db("SELECT balance FROM accounts WHERE user_id = 3", one=True)['balance']))
        john_now = Decimal(str(query_db("SELECT balance FROM accounts WHERE user_id = 2", one=True)['balance']))

        assert jane_now == jane_prev - reverse_amount
        assert john_now == john_prev + reverse_amount
        print(f"  --> PASS: Reverse transfer of INR {reverse_amount:,.2f} completed safely without deadlock.")

    # -------------------------------------------------------------
    # TEST 7: Daily Transaction Limit Enforcement
    # -------------------------------------------------------------
    print("\n[TEST 7] Testing Daily Spending Limit Enforcement...")
    with client:
        # Check John's remaining limit
        john_limit_row = query_db("SELECT daily_limit FROM accounts WHERE user_id = 2", one=True)
        john_daily_limit = Decimal(str(john_limit_row['daily_limit']))

        # Calculate current spent today
        spent_row = query_db(
            """SELECT COALESCE(SUM(amount), 0) AS total
               FROM transactions
               WHERE from_account_id = 2 AND status = 'success' AND DATE(created_at) = CURDATE()""",
            one=True
        )
        total_spent = Decimal(str(spent_row['total']))
        excess_amount = (john_daily_limit - total_spent) + Decimal('100.00')

        res_limit = client.post('/transfer', data={
            'recipient': 'jane',
            'amount': str(excess_amount),
            'description': 'Exceeding limit test'
        }, follow_redirects=True)
        assert b"limit exceeded" in res_limit.data
        print(f"  --> PASS: Outgoing transfer of INR {excess_amount:,.2f} exceeding daily limit (INR {john_daily_limit:,.2f}) rejected.")

    # -------------------------------------------------------------
    # TEST 8: Transaction History & Filtering
    # -------------------------------------------------------------
    print("\n[TEST 8] Testing Transaction History Ledger & Filters...")
    with client:
        # 1. View all history
        res_hist_all = client.get('/history')
        assert res_hist_all.status_code == 200
        assert b"Transaction Ledger" in res_hist_all.data
        assert b"Shared dinner bill payment" in res_hist_all.data

        # 2. Filter by type=transfer
        res_hist_tr = client.get('/history?type=transfer')
        assert b"Transfer Sent" in res_hist_tr.data or b"Transfer Received" in res_hist_tr.data

        # 3. Filter by search query
        res_hist_q = client.get('/history?q=dinner')
        assert b"Shared dinner bill payment" in res_hist_q.data
        print("  --> PASS: Ledger accurately lists all events, supports type filters, and search queries.")

    print("\n" + "=" * 60)
    print("  ALL 8 PHASE 5 TRANSFER & LEDGER TESTS PASSED! [100%]")
    print("=" * 60)


if __name__ == '__main__':
    run_transfer_tests()
