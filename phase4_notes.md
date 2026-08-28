# PHASE 4 — Wallet Operations & SQL Concurrency Control
## What Was Done + Interview Defense Guide

---

## What Was Built In This Phase

| File | Purpose |
|---|---|
| `routes/wallet.py` | Blueprint containing `/dashboard`, `/deposit`, and `/withdraw` routes with SQL transactions, `SELECT ... FOR UPDATE`, and audit logging |
| `templates/wallet/dashboard.html` | Digital wallet dashboard displaying active balance, account number, status badge, quick actions, and recent activity |
| `templates/wallet/deposit.html` | Deposit funds interface with quick amount presets and description |
| `templates/wallet/withdraw.html` | Withdrawal interface with available balance check and quick amount presets |
| `templates/base.html` | Updated navbar with direct "Dashboard" link for authenticated users |
| `app.py` | Registered `wallet_bp` and added intelligent redirect to `/dashboard` for logged-in users |
| `test_wallet.py` | Automated test suite verifying 8 test cases across balance checks, deposits, withdrawals, overdraft protection, and account status enforcement |

---

## Deep-Dive Interview Defense: Transactions & Concurrency

---

### 1. The Transaction Flow (Deposit vs. Withdrawal)

#### A. Deposit Lifecycle
```text
Client Request (₹1,500.00)
    │
    ▼
1. Validate input: Decimal > 0, max 2 decimal places, sanity limit.
2. SELECT id, balance, status FROM accounts WHERE user_id = %s FOR UPDATE
   └── Acquires Exclusive Row-Level Lock on this account.
3. Check status == 'active'.
4. UPDATE accounts SET balance = balance + 1500.00 WHERE id = account_id
5. INSERT INTO transactions (ref, from_account_id=NULL, to_account_id=id, amount=1500.00, ...)
6. INSERT INTO audit_logs (user_id, action='DEPOSIT', ...)
7. COMMIT (Atomically persists changes and releases the row lock)
    │
    ▼ (If any step throws an error)
   ROLLBACK (Reverts all changes cleanly; balance remains untouched)
```

#### B. Withdrawal Lifecycle
```text
Client Request (₹750.00)
    │
    ▼
1. Validate input: Decimal > 0, max 2 decimal places.
2. SELECT id, balance, status FROM accounts WHERE user_id = %s FOR UPDATE
   └── Acquires Exclusive Row-Level Lock.
3. Check status == 'active'.
4. Check current_balance >= requested_amount:
   ├── If balance < amount: ROLLBACK, return "Insufficient funds" alert.
   └── If balance >= amount: Proceed to step 5.
5. UPDATE accounts SET balance = balance - 750.00 WHERE id = account_id
6. INSERT INTO transactions (ref, from_account_id=id, to_account_id=NULL, amount=750.00, ...)
7. INSERT INTO audit_logs (user_id, action='WITHDRAWAL', ...)
8. COMMIT (Atomically persists changes and releases the row lock)
```

---

### 2. ACID Properties in SecurePay

**Q: How does SecurePay fulfill the ACID properties of database transactions?**

> - **Atomicity (All or Nothing)**:
>   Balance update, financial ledger insertion (`transactions`), and security trail (`audit_logs`) are bound in one transaction block. If an exception occurs (e.g. database disconnect or validation error), `conn.rollback()` ensures no partial deduction or ghost deposit occurs.
>
> - **Consistency (Valid State)**:
>   The database transitions from one valid financial state to another. Constraints like `CHECK (balance >= 0)`, `CHECK (amount > 0)`, and foreign keys (`FK accounts.user_id -> users.id`) guarantee corrupt states cannot be committed.
>
> - **Isolation (No Interference)**:
>   Using MySQL InnoDB's row-level locking (`SELECT ... FOR UPDATE`), concurrent transactions operating on the same wallet execute sequentially without dirty reads or non-repeatable reads.
>
> - **Durability (Permanence)**:
>   Once `conn.commit()` is called, MySQL's Write-Ahead Log (InnoDB redo log) guarantees the changes survive server crashes or power failures.

---

### 3. Concurrency Control & The Race Condition (Double-Spending Attack)

**Q: What is a Race Condition in a wallet system, and how did you prevent it?**

> **The Vulnerability (Without Row Locking):**
> Imagine Alice has **₹1,000** in her wallet.
> She submits two simultaneous withdrawal requests of **₹800** at the exact same millisecond:
>
> ```text
> Request 1 (Thread A)               Request 2 (Thread B)
> ────────────────────               ────────────────────
> Read balance: ₹1,000               Read balance: ₹1,000
> Check: 1000 >= 800 (True)          Check: 1000 >= 800 (True)
> New balance: 1000 - 800 = 200      New balance: 1000 - 800 = 200
> Update balance to ₹200             Update balance to ₹200
> ─────────────────────────────────────────────────────────────
> Result: Alice withdrew ₹1,600 from a ₹1,000 balance! (Double-Spending)
> ```
>
> **The Solution in SecurePay (`SELECT ... FOR UPDATE`):**
> We use **Pessimistic Row-Level Locking**:
> ```sql
> SELECT id, balance, status FROM accounts WHERE user_id = %s FOR UPDATE;
> ```
> 1. Thread A acquires an exclusive lock on Alice's row in `accounts`.
> 2. Thread B attempts to read Alice's row with `FOR UPDATE` but is **blocked** by MySQL until Thread A commits or rolls back.
> 3. Thread A deducts ₹800, sets balance to ₹200, and commits.
> 4. Thread B now unblocks and reads the updated balance: **₹200**.
> 5. Thread B's check (`200 >= 800`) fails $\rightarrow$ rejects request with *"Insufficient funds"*.

---

### 4. Pessimistic vs. Optimistic Locking

**Q: Why choose Pessimistic Locking (`FOR UPDATE`) over Optimistic Locking (version columns)?**
> | Strategy | How It Works | Best For | Why used in SecurePay |
> |---|---|---|---|
> | **Pessimistic Locking** (`FOR UPDATE`) | Locks the row immediately on read; prevents any other writer from touching it until commit. | High-contention financial systems where conflicts must be strictly serialized. | **Selected**: Guarantees zero race conditions during critical balance updates without retrying failed requests. |
> | **Optimistic Locking** (`version` column) | Reads without locking. On update: `UPDATE ... WHERE id = %s AND version = %s`. If 0 rows affected, retry. | High-read, low-write systems (e.g. blog posts, product catalogs). | Rejected: In high-concurrency wallet withdrawals, multiple failed attempts require complex retry loops on the application layer. |

---

### 5. Floating Point vs. Exact Decimal Arithmetic

**Q: Why is `Decimal` used in Python and `DECIMAL(15,2)` in MySQL?**
> Standard floating-point (`float`) uses IEEE 754 binary representation, which cannot represent base-10 fractions (like 0.1 or 0.01) precisely:
> ```python
> # Floating point bug:
> 0.1 + 0.2  # Returns 0.30000000000000004
>
> # Decimal (Exact):
> from decimal import Decimal
> Decimal('0.1') + Decimal('0.2')  # Returns Decimal('0.3')
> ```
> In SecurePay:
> - User input is converted to `Decimal(amount_str)`.
> - Python validates `amount.as_tuple().exponent >= -2` to prohibit sub-cent/sub-paisa fractions (e.g., ₹10.005).
> - MySQL stores the exact balance in `DECIMAL(15, 2)`, completely eliminating cumulative financial discrepancies.

---

### 6. Authorization & IDOR Prevention

**Q: How do you prevent a malicious user from depositing or withdrawing from someone else's account?**
> We strictly bind operations to the authenticated user's session:
> ```python
> user_id = session['user_id']
> cursor.execute("SELECT id FROM accounts WHERE user_id = %s", (user_id,))
> ```
> We **NEVER** accept `account_id` or `user_id` as form inputs (`request.form.get('account_id')`).
> An attacker cannot tamper with hidden inputs or URL parameters to manipulate another person's wallet (preventing Insecure Direct Object Reference / IDOR vulnerabilities).

---

## Automated Test Verification Results (`test_wallet.py`)

| # | Test Case | Expected Behavior | Result |
|---|---|---|---|
| 1 | **Unauthorized Protection** | Unauthenticated requests to `/dashboard`, `/deposit`, `/withdraw` redirect to `/login`. | **PASS** ✅ |
| 2 | **Dashboard Display** | Renders wallet account number, balance, status badge, and recent activity. | **PASS** ✅ |
| 3 | **Deposit Validation** | Rejects negative, zero, non-numeric, and invalid fractional inputs. | **PASS** ✅ |
| 4 | **Successful Deposit** | Adds funds, creates `deposit` transaction row with UUID ref, writes `DEPOSIT` audit log. | **PASS** ✅ |
| 5 | **Withdrawal Validation** | Rejects negative, zero, and malformed withdrawal requests. | **PASS** ✅ |
| 6 | **Insufficient Funds** | Rejects overdraft requests with flash alert; balance remains strictly untouched. | **PASS** ✅ |
| 7 | **Successful Withdrawal** | Deducts funds, creates `withdrawal` transaction row, writes `WITHDRAWAL` audit log. | **PASS** ✅ |
| 8 | **Suspended Account Security** | Prohibits deposits and withdrawals on locked/suspended accounts (User Bob). | **PASS** ✅ |
