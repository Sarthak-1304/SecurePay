# PHASE 5 — Peer-to-Peer Transfers, Daily Limits & Ledger
## What Was Done + Interview Defense Guide

---

## What Was Built In This Phase

| File | Purpose |
|---|---|
| `routes/wallet.py` | Implemented `/transfer` with atomic two-account transfer, deterministic lock ordering, daily limit checking, and `/history` with filtering and search |
| `templates/wallet/transfer.html` | Peer-to-peer transfer interface with recipient auto-resolution, real-time balance and daily limit allowance cards, and quick presets |
| `templates/wallet/history.html` | Immutable financial ledger table with transaction type filter tabs (`all`, `deposit`, `withdrawal`, `transfer`), keyword search, and counterparty metadata |
| `templates/wallet/dashboard.html` | Activated "Transfer Money" button and added quick link to full transaction ledger |
| `templates/base.html` | Added "Transfer" and "History" navigation items in top navbar for authenticated users |
| `test_transfer.py` | Automated test suite verifying 8 test cases (self-transfers, non-existent recipients, suspended users, insufficient balance, atomic balance movements, deadlock safety, daily limits, and ledger filtering) |

---

## Technical Deep-Dive & Interview Defense Guide

---

### 1. Atomic Two-Account Transfer Flow

**Q: How does SecurePay execute a money transfer between User A and User B?**

> In `routes/wallet.py`, a transfer is executed as a **single, all-or-nothing SQL transaction**:
>
> ```text
> User A (Sender) requests ₹1,000 to User B (Receiver)
>     │
>     ▼
> 1. Input Validation: Verify amount is positive Decimal with max 2 decimal places.
> 2. Recipient Resolution: Look up recipient by username, email, or account number (ACC0000X).
> 3. Business Policy Checks:
>    ├── Sender != Receiver (Reject self-transfers)
>    └── Sender and Receiver accounts must be 'active' and not locked.
> 4. Deadlock-Safe Row Locking:
>    Acquire exclusive locks on BOTH accounts in sorted numerical ID order:
>    `SELECT ... WHERE id IN (%s, %s) ORDER BY id FOR UPDATE`
> 5. Daily Spending Limit Check:
>    Calculate today's outgoing volume: `SELECT SUM(amount) ... WHERE DATE(created_at) = CURDATE()`.
>    If `spent_today + 1000 > daily_limit`: ROLLBACK & abort.
> 6. Balance Check:
>    If `sender_balance < 1000`: ROLLBACK & abort.
> 7. Balance Updates:
>    ├── Debit sender:   `UPDATE accounts SET balance = balance - 1000 WHERE id = sender_id`
>    └── Credit receiver: `UPDATE accounts SET balance = balance + 1000 WHERE id = receiver_id`
> 8. Ledger Recording:
>    `INSERT INTO transactions (ref, from_account_id, to_account_id, type='transfer', amount=1000, status='success')`
> 9. Audit Logging:
>    `INSERT INTO audit_logs (user_id, action='TRANSFER', ...)`
> 10. COMMIT (Atomically persists both balance updates and releases row locks)
>     │
>     ▼ (If ANY query or validation fails)
>    ROLLBACK (Both balances remain completely unchanged)
> ```

---

### 2. ACID Properties in P2P Transfers

**Q: Explain how each ACID property is guaranteed during a transfer.**

> - **Atomicity**:
>   Money cannot leave User A's wallet unless it arrives in User B's wallet. If the server crashes or the network disconnects after debiting User A, the transaction is **rolled back**; User A never loses money into thin air.
>
> - **Consistency**:
>   The total amount of money in the system remains invariant: $\Delta \text{Balance}_A + \Delta \text{Balance}_B = (-1000) + (+1000) = 0$.
>   Database constraints (`CHECK (balance >= 0)`) ensure sender balance cannot dip below zero.
>
> - **Isolation**:
>   Row-level locks (`FOR UPDATE`) isolate this transfer from other concurrent transfers or withdrawals involving either account. Other sessions see either the pre-transfer state or the post-transfer state, never an intermediate state.
>
> - **Durability**:
>   When `conn.commit()` returns, MySQL's InnoDB transaction log (write-ahead redo log) commits to non-volatile storage. The transfer survives server restarts or crashes.

---

### 3. Deadlock Prevention: Deterministic Lock Ordering

**Q: What is a Database Deadlock in money transfers, and how did you prevent it?**

> **The Deadlock Scenario (Without Lock Ordering):**
> Suppose User 1 (ID 10) transfers ₹500 to User 2 (ID 20), while User 2 simultaneously transfers ₹300 to User 1.
>
> ```text
> Time    Thread A (User 1 -> User 2)          Thread B (User 2 -> User 1)
> ────    ───────────────────────────          ───────────────────────────
> T1      Locks Account 10 (Sender)            Locks Account 20 (Sender)
> T2      Tries to lock Account 20 (Receiver)  Tries to lock Account 10 (Receiver)
>         [BLOCKED: Waiting for Thread B]      [BLOCKED: Waiting for Thread A]
> ──────────────────────────────────────────────────────────────────────────
> Result: DEADLOCK! Circular wait. MySQL must abort and kill one transaction.
> ```
>
> **The Solution in SecurePay (Deterministic Lock Ordering):**
> We eliminate the circular wait condition by **always locking account rows in ascending numerical ID order**:
>
> ```python
> first_id, second_id = sorted([sender_acc_id, receiver_acc_id])
>
> cursor.execute(
>     """SELECT id, balance, status, daily_limit
>        FROM accounts
>        WHERE id IN (%s, %s)
>        ORDER BY id
>        FOR UPDATE""",
>     (first_id, second_id)
> )
> ```
>
> Now, both Thread A and Thread B will attempt to lock **Account 10 first**, then **Account 20 second**:
> 1. Thread A acquires lock on Account 10.
> 2. Thread B tries to lock Account 10 and is blocked *before* acquiring lock 20.
> 3. Thread A acquires lock on Account 20, completes transfer, and commits (releasing both locks).
> 4. Thread B now acquires lock on Account 10, then Account 20, and completes cleanly.
>
> **No circular wait $\rightarrow$ Zero deadlocks.**

---

### 4. Daily Spending Limit Enforcement

**Q: How does the system compute and enforce the daily limit?**
> Each wallet has a `daily_limit` (default ₹50,000.00).
> Before executing any outgoing withdrawal or transfer, SecurePay aggregates today's completed outgoing transactions:
>
> ```sql
> SELECT COALESCE(SUM(amount), 0) AS total_spent
> FROM transactions
> WHERE from_account_id = %s
>   AND status = 'success'
>   AND DATE(created_at) = CURDATE();
> ```
>
> If `total_spent + requested_amount > daily_limit`, the transaction is rolled back with an informative message showing the user their remaining daily allowance.
>
> **Why use `CURDATE()` in SQL?**
> The database evaluates current date uniformly according to server time, preventing client-side timezone manipulation.

---

### 5. Transaction Ledger & Indexing

**Q: How is the transaction ledger optimized for high read performance?**
> In `routes/wallet.py`, `/history` retrieves all incoming and outgoing transactions using a single `JOIN` query:
> ```sql
> SELECT t.*, a_from.account_number, u_from.username, a_to.account_number, u_to.username
> FROM transactions t
> LEFT JOIN accounts a_from ON t.from_account_id = a_from.id
> LEFT JOIN users u_from ON a_from.user_id = u_from.id
> LEFT JOIN accounts a_to ON t.to_account_id = a_to.id
> LEFT JOIN users u_to ON a_to.user_id = u_to.id
> WHERE (t.from_account_id = %s OR t.to_account_id = %s)
> ORDER BY t.created_at DESC;
> ```
>
> **Index Support (from `schema.sql`)**:
> - `idx_txn_from_account (from_account_id)` $\rightarrow$ Fast lookup for sent transactions.
> - `idx_txn_to_account (to_account_id)` $\rightarrow$ Fast lookup for received transactions.
> - `idx_txn_created_at (created_at)` $\rightarrow$ Fast sorting and daily aggregation (`CURDATE()`).
> - `idx_txn_type (transaction_type)` $\rightarrow$ Instant filtering by Deposit/Withdrawal/Transfer.

---

## Automated Test Verification Results (`test_transfer.py`)

| # | Test Case | Expected Behavior | Result |
|---|---|---|---|
| 1 | **Unauthorized Protection** | Unauthenticated requests to `/transfer` and `/history` redirect to `/login`. | **PASS** ✅ |
| 2 | **Self-Transfer Prevention** | Rejects transfers where sender == receiver (by username or account number). | **PASS** ✅ |
| 3 | **Recipient Validation** | Rejects non-existent recipients and transfers to suspended accounts (Bob). | **PASS** ✅ |
| 4 | **Insufficient Balance** | Rejects transfers exceeding available balance; zero balance change. | **PASS** ✅ |
| 5 | **Atomic P2P Transfer** | Exactly debits sender, credits receiver, writes ledger row, writes audit log. | **PASS** ✅ |
| 6 | **Bidirectional Deadlock Safety** | Reverse transfer (Jane -> John) executes concurrently without deadlocking. | **PASS** ✅ |
| 7 | **Daily Limit Enforcement** | Rejects outgoing transfer exceeding the remaining ₹50,000.00 daily allowance. | **PASS** ✅ |
| 8 | **Ledger Listing & Filters** | Accurately renders transaction history, supports `?type=transfer` and keyword search. | **PASS** ✅ |
