"""
run_all_tests.py — Unified Master Test Suite Runner for SecurePay

Executes all 6 specialized test suites:
1. Authentication & Security (test_auth.py)
2. Wallet Operations (test_wallet.py)
3. Peer-to-Peer Transfers & Daily Limits (test_transfer.py)
4. Audit Logging & Tenant Data Isolation (test_audit_history.py)
5. Administrator RBAC & User Management (test_admin.py)
6. Concurrency, Row Locking & Deadlock Safety (test_concurrency.py)
"""

import sys
import time

from test_auth import run_auth_tests
from test_wallet import run_wallet_tests
from test_transfer import run_transfer_tests
from test_audit_history import run_audit_history_tests
from test_admin import run_admin_tests
from test_concurrency import run_concurrency_tests


def main():
    print("=" * 70)
    print("        SECUREPAY MASTER AUTOMATED TEST SUITE RUNNER")
    print("=" * 70)
    start_time = time.time()

    suites = [
        ("Authentication & Security", run_auth_tests),
        ("Wallet Operations", run_wallet_tests),
        ("P2P Transfers & Daily Limits", run_transfer_tests),
        ("Audit Logging & Isolation", run_audit_history_tests),
        ("Admin Panel & RBAC", run_admin_tests),
        ("Concurrency & Deadlock Safety", run_concurrency_tests),
    ]

    passed_count = 0
    total_count = len(suites)

    for name, test_func in suites:
        try:
            test_func()
            passed_count += 1
        except Exception as e:
            print(f"\n[FAIL] Test suite '{name}' encountered an error: {e}")
            sys.exit(1)

    duration = time.time() - start_time
    print("\n" + "=" * 70)
    print(f"  ALL {passed_count}/{total_count} TEST SUITES PASSED PERFECTLY! [100%]")
    print(f"  Total Execution Time: {duration:.2f} seconds")
    print("=" * 70)


if __name__ == '__main__':
    main()
