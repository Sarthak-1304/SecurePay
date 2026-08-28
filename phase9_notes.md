# PHASE 9 — Test Plan, Concurrency Verification & Interview Demo Guide
## Practical Test Plan + Master Automated Suite + Live Interview Demo Script

---

## 1. Practical Test Plan Matrix

| Functional Area | Test Case Description | Expected Result | Automated Test |
|---|---|---|---|
| **AUTHENTICATION** | **User Registration** | Creates user in `users`, hashes password with Werkzeug `scrypt`, provisions wallet `ACC0000X`, logs `REGISTER`. | `test_auth.py` (Test 1) ✅ |
| | **Duplicate Registration** | Rejects registration when username or email is already in use. | `test_auth.py` (Test 2) ✅ |
| | **User Login** | Authenticates credentials, regenerates session, logs `LOGIN_SUCCESS`. | `test_auth.py` (Test 3) ✅ |
| | **Wrong Password** | Increments `failed_logins` counter, flashes warning with remaining attempts. | `test_auth.py` (Test 5) ✅ |
| | **Brute-Force Lockout** | Automatically locks account (`is_locked=TRUE`) and suspends wallet on 5th failed attempt. | `test_auth.py` (Test 6) ✅ |
| | **Login Reset on Success** | Resets `failed_logins` back to 0 upon successful authentication. | `test_auth.py` (Test 7) ✅ |
| | **Logout** | Destroys session (`session.clear()`), redirects to `/login`. | `test_auth.py` (Test 4) ✅ |
| **ACCOUNT & WALLET** | **Auto Account Creation** | User registration automatically generates single active wallet. | `test_auth.py` (Test 1) ✅ |
| | **Balance Display** | Formats balance to 2 decimal places with currency symbol (`₹10,500.00`). | `test_wallet.py` (Test 2) ✅ |
| **DEPOSIT** | **Valid Positive Deposit** | Locks row, increases balance, writes ledger row, writes audit log, commits. | `test_wallet.py` (Test 4) ✅ |
| | **Zero Deposit** | Rejected with *"Deposit amount must be greater than zero."* | `test_wallet.py` (Test 3) ✅ |
| | **Negative Deposit** | Rejected by Python validation & SQL constraint `CHECK (amount > 0)`. | `test_wallet.py` (Test 3) ✅ |
| | **Database Rollback** | Any SQL failure triggers `conn.rollback()`; balance stays intact. | `test_wallet.py` (Test 4) ✅ |
| **WITHDRAWAL** | **Valid Withdrawal** | Locks row, verifies balance, deducts amount, writes ledger row, commits. | `test_wallet.py` (Test 7) ✅ |
| | **Insufficient Balance** | Overdraft attempt rejected; zero deduction occurs. | `test_wallet.py` (Test 6) ✅ |
| | **Zero / Negative Amount** | Rejected before database query. | `test_wallet.py` (Test 5) ✅ |
| | **Suspended Wallet Restriction** | Locked/suspended accounts prohibited from withdrawing funds. | `test_wallet.py` (Test 8) ✅ |
| **P2P TRANSFER** | **Valid Atomic Transfer** | Debits sender, credits receiver, creates ledger record in single transaction. | `test_transfer.py` (Test 5) ✅ |
| | **Insufficient Balance** | Transfer exceeding sender balance rejected with rollback. | `test_transfer.py` (Test 4) ✅ |
| | **Invalid / Suspended Recipient** | Rejects non-existent users and suspended recipients (Bob). | `test_transfer.py` (Test 3) ✅ |
| | **Self-Transfer Defense** | Rejects transfer where sender == recipient. | `test_transfer.py` (Test 2) ✅ |
| | **Daily Limit Enforcement** | Aggregates `CURDATE()` spending and blocks transfers exceeding daily limit. | `test_transfer.py` (Test 7) ✅ |
| | **Concurrent Double-Spend** | 2 simultaneous requests exceeding balance $\rightarrow$ exactly 1 succeeds, 1 fails. | `test_concurrency.py` (Test 1) ✅ |
| | **Bidirectional Deadlock Safety** | User A $\leftrightarrow$ User B concurrent transfers succeed without deadlock. | `test_concurrency.py` (Test 2) ✅ |
| **AUTHORIZATION & RBAC** | **User Data Isolation (IDOR)** | User only sees their own transactions; cannot query other wallets. | `test_audit_history.py` (Test 1) ✅ |
| | **User Accessing Admin Routes** | Non-admin user visiting `/admin/*` is blocked with Access Denied (302). | `test_admin.py` (Test 1) ✅ |
| | **Admin Route Access** | User with `role = 'admin'` accesses dashboard, user directory, audit logs. | `test_admin.py` (Test 2) ✅ |
| | **Admin Self-Lock Prevention** | Backend rule prevents admin from locking their own account. | `test_admin.py` (Test 5) ✅ |
| **AUDIT & COMPLIANCE** | **Login & Failed Login Logs** | Records IP and timestamp for login successes and wrong password attempts. | `test_audit_history.py` (Test 3) ✅ |
| | **Transfer Logs** | Logs sender, receiver, amount, and reference code. | `test_audit_history.py` (Test 3) ✅ |
| | **Admin Action Logs** | Logs administrative lock and unlock events. | `test_admin.py` (Test 4) ✅ |
| | **Credential Sanitization** | Sanitizer guarantees passwords never enter audit logs. | `test_audit_history.py` (Test 3) ✅ |

---

## 2. Master Automated Test Suite Summary (`run_all_tests.py`)

Run the full automated test suite anytime with:
```powershell
py run_all_tests.py
```

```text
======================================================================
        SECUREPAY MASTER AUTOMATED TEST SUITE RUNNER
======================================================================
  [SUITE 1] Authentication & Security (test_auth.py)          --> 7/7 PASSED ✅
  [SUITE 2] Wallet Operations (test_wallet.py)                --> 8/8 PASSED ✅
  [SUITE 3] P2P Transfers & Daily Limits (test_transfer.py)    --> 8/8 PASSED ✅
  [SUITE 4] Audit Logging & Tenant Isolation (test_audit_history.py) --> 4/4 PASSED ✅
  [SUITE 5] Administrator RBAC & Oversight (test_admin.py)   --> 6/6 PASSED ✅
  [SUITE 6] Concurrency & Deadlock Safety (test_concurrency.py) --> 2/2 PASSED ✅
======================================================================
  ALL 35/35 AUTOMATED TESTS PASSED PERFECTLY! [100%]
  Total Execution Time: ~4.4 seconds
======================================================================
```

---

## 3. Live Interview Manual Demo Script & Checklist

Use this step-by-step checklist during a live technical interview or demo to impress the interviewer.

### Demo Setup & Pre-Seeded Accounts

| User | Username / Email | Password | Role | Wallet Account | Initial Status |
|---|---|---|---|---|---|
| **Admin** | `admin` / `admin@securepay.com` | `admin123` | `admin` | `ACC00001` | Active (Admin) |
| **John Doe** | `john` / `john@example.com` | `password123` | `user` | `ACC00002` | Active |
| **Jane Smith** | `jane` / `jane@example.com` | `password123` | `user` | `ACC00003` | Active |
| **Bob Suspended** | `bob` / `bob@example.com` | `password123` | `user` | `ACC00004` | Locked / Suspended |

---

### Step-by-Step Demo Flow

#### Step 1: Start the Development Server
- Open Terminal and run:
  ```powershell
  py app.py
  ```
- Open browser at `http://127.0.0.1:5000`.

---

#### Step 2: Demonstrate Registration & Defense-in-Depth
1. Click **"Get Started"** / **"Register"**.
2. Try registering with an invalid username (e.g. `jo` or `user@name!`).
   - *Result*: Real-time rejection (3-30 characters alphanumeric only).
3. Try registering with existing username `john`.
   - *Result*: Rejection (*"Username is already taken"*).
4. Register a new user: `charlie` / `charlie@example.com` / `Secret123!`.
   - *Result*: User is created, wallet `ACC00005` is auto-provisioned, password is encrypted with `scrypt`, and `REGISTER` event is logged.
   - **Interview Talking Point**: *"Notice how account creation is a single atomic SQL transaction. Both the user record and wallet account are created together, preventing orphan accounts."*

---

#### Step 3: Demonstrate Brute-Force Protection & Account Locking
1. Go to `/login`.
2. Try logging in as `charlie` with a wrong password `wrongpass` 4 times.
   - *Result*: Flash warning: *"Invalid username/email or password. (Warning: 4 of 5 failed attempts)"*.
3. Enter wrong password a 5th time.
   - *Result*: Flash alert: *"Your account has been locked due to 5 consecutive failed login attempts."*
4. Attempt a 6th login.
   - *Result*: Immediate block (*"Your account is locked... Please contact an administrator"*).
   - **Interview Talking Point**: *"This prevents brute-force credential stuffing without exposing whether the username exists."*

---

#### Step 4: Demonstrate Admin RBAC & Account Unlocking
1. Log in as `admin` (password: `admin123`).
2. Notice the yellow **"Admin"** dropdown in the navigation bar.
3. Click **"Admin Panel"** (`/admin/dashboard`).
   - Show platform statistics (Active Users, Locked Accounts, Total System Deposits).
4. Click **"Manage Users"** (`/admin/users`).
   - Locate user `@charlie` showing a red **Locked** badge.
5. Click **"Unlock"** next to Charlie.
   - *Result*: Charlie is restored to **Active** status and failed logins reset to 0.
   - **Interview Talking Point**: *"Backend authorization is enforced with an `@admin_required` decorator. If a normal user types `/admin/users`, they are immediately blocked with Access Denied."*

---

#### Step 5: Demonstrate Deposits, Withdrawals & Overdraft Prevention
1. Log out of Admin and log in as `john` (password: `password123`).
2. Click **"Deposit"** (`/deposit`):
   - Try depositing `-500` or `0` $\rightarrow$ Rejected.
   - Deposit `₹2,000.00` $\rightarrow$ Balance updates instantly with success confirmation.
3. Click **"Withdraw"** (`/withdraw`):
   - Try withdrawing `₹999,999.00` $\rightarrow$ Rejected (*"Insufficient funds! Available balance is ₹..."*).
   - Withdraw `₹500.00` $\rightarrow$ Balance safely deducted.
   - **Interview Talking Point**: *"All balance mutations use `SELECT ... FOR UPDATE` row locks to prevent Double-Spending race conditions."*

---

#### Step 6: Demonstrate Atomic Peer-to-Peer Transfer
1. Click **"Transfer"** (`/transfer`):
   - Transfer to `jane` (Amount: `₹1,000.00`, Note: `Lunch share`).
   - *Result*: Flash message with transaction reference UUID. John's balance decreases by ₹1,000, Jane's balance increases by ₹1,000.
2. Try transferring to self (`john`) $\rightarrow$ Rejected (*"You cannot transfer money to your own wallet"*).
3. Try transferring to suspended user `bob` $\rightarrow$ Rejected (*"Recipient account is suspended"*).
4. **Interview Talking Point**: *"P2P transfers use Deterministic Lock Ordering by sorting account IDs before acquiring row locks, mathematically preventing deadlocks during concurrent transfers."*

---

#### Step 7: Demonstrate Filterable Ledger & System Audit Trail
1. Click **"History"** (`/history`):
   - Show transaction ledger with counterparties (`To: Jane Smith (@jane)`).
   - Filter by **"Transfers"** and search by note `Lunch`.
2. Log in as `admin` and open **"Security Audit Logs"** (`/admin/audit-logs`):
   - Show the immutable audit trail displaying `LOGIN_SUCCESS`, `LOGIN_FAILED`, `ACCOUNT_LOCKED`, `ACCOUNT_UNLOCKED`, and `TRANSFER` with IP addresses and timestamps.
   - **Interview Talking Point**: *"All audit entries are sanitized so sensitive credentials never leak into persistent storage."*

---

## 4. Technical Defense Summary for Interviews

**Q: How did you test concurrency and race conditions?**
> *"In `test_concurrency.py`, we used Python's `threading` library to fire simultaneous HTTP requests against the live database:*
> 1. *In the Double-Spend test, two threads attempted to withdraw funds simultaneously when the balance could only satisfy one. Thanks to `SELECT ... FOR UPDATE` pessimistic locking, one succeeded and the other was cleanly rejected.*
> 2. *In the Deadlock test, Thread 1 transferred from User A to User B while Thread 2 simultaneously transferred from User B to User A. Because we enforce Deterministic Lock Ordering (`sorted([id_a, id_b])`), both threads acquired locks in the same order, completing with zero deadlocks."*
