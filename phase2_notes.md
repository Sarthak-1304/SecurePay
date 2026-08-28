# PHASE 2 — Database Design & Schema
## What Was Done + Interview Defense Guide

---

## What Was Built In This Phase

| File | Purpose |
|---|---|
| `schema.sql` | Complete database schema — 4 tables with all constraints |
| `seed.sql` | Sample data — 4 users, 4 accounts, 5 transactions, 16 audit logs |
| `seed.py` | Python-based alternative seeder (updated) |

---

## Database Design Overview

### The 4 Tables

```
users ──── 1:1 ──── accounts ──── 1:N ──── transactions
  │
  └─── 1:N ──── audit_logs
```

| Table | Stores | Row Count (seed) |
|---|---|---|
| `users` | Login credentials, role, lock status | 4 |
| `accounts` | Wallet balance, account number, daily limit | 4 |
| `transactions` | Every deposit, withdrawal, transfer | 5 |
| `audit_logs` | Security events (logins, locks, admin actions) | 16 |

---

## Table-by-Table Interview Defense

---

### TABLE: `users`

```sql
CREATE TABLE users (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    username        VARCHAR(50)  NOT NULL UNIQUE,
    email           VARCHAR(100) NOT NULL UNIQUE,
    password_hash   VARCHAR(256) NOT NULL,
    full_name       VARCHAR(100) NOT NULL,
    role            ENUM('user', 'admin') NOT NULL DEFAULT 'user',
    is_locked       BOOLEAN NOT NULL DEFAULT FALSE,
    failed_logins   INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;
```

**Q: Why is `username` both NOT NULL and UNIQUE?**
> NOT NULL: Every user must have a username (can't be empty).
> UNIQUE: No two users can have the same username.
> Together: every user has a non-empty, non-duplicate login name.
> MySQL creates an index automatically for UNIQUE columns, so lookups during
> login (`WHERE username = ?`) are fast — O(log n) instead of O(n).

**Q: Why `password_hash VARCHAR(256)` and not `CHAR(64)` (SHA-256 length)?**
> We use Werkzeug's `generate_password_hash()` which produces output like:
> `scrypt:32768:8:1$salt$hash` — this is variable-length (not fixed 64 chars).
> VARCHAR(256) accommodates any hash format Werkzeug uses (PBKDF2, scrypt, etc.)
> without breaking if the library changes its output format.

**Q: Why store `password_hash` and not the plaintext password?**
> If the database is breached, attackers get the hash, not the actual password.
> Werkzeug uses **scrypt** (or PBKDF2) with a random salt, which means:
> 1. Two users with the same password get DIFFERENT hashes (because of salt)
> 2. Brute-force is extremely slow (scrypt is intentionally computationally expensive)
> 3. Rainbow tables don't work (because of salt)

**Q: Why `ENUM('user', 'admin')` and not a `roles` table?**
> For only 2 roles, a separate table is over-engineering. ENUM:
> - Restricts values at the database level (can't insert 'superadmin' or typos)
> - Takes only 1 byte of storage (vs JOIN to a roles table)
> - Is simpler to query (`WHERE role = 'admin'` vs JOIN)
> If we needed 10+ roles with permissions, then yes — a `roles` table with a
> many-to-many relationship would be better. But for 2 roles, ENUM is ideal.

**Q: Why track `failed_logins` as a counter instead of a separate table?**
> We only need to know "has this user failed 5+ times?" — a counter answers that.
> The audit_logs table already records each individual failed attempt with timestamps
> and IP addresses. A separate `login_attempts` table would duplicate that data.

**Q: What does `ON UPDATE CURRENT_TIMESTAMP` do?**
> It automatically updates the `updated_at` column whenever ANY column in that row
> is modified. This gives us a "last modified" timestamp without any application code.

---

### TABLE: `accounts`

```sql
CREATE TABLE accounts (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    user_id         INT NOT NULL UNIQUE,
    account_number  VARCHAR(20) NOT NULL UNIQUE,
    balance         DECIMAL(15, 2) NOT NULL DEFAULT 0.00,
    status          ENUM('active', 'suspended', 'closed') NOT NULL DEFAULT 'active',
    daily_limit     DECIMAL(15, 2) NOT NULL DEFAULT 50000.00,
    ...
    CONSTRAINT fk_accounts_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT,
    CONSTRAINT chk_balance_non_negative CHECK (balance >= 0)
) ENGINE=InnoDB;
```

**Q: Why separate `accounts` from `users`? Each user has only one account.**
> This is a deliberate **normalization** decision:
> 1. **Separation of concerns**: Auth data (password, role) stays in `users`.
>    Financial data (balance, transactions) stays in `accounts`.
> 2. **Extensibility**: In real banking, users have multiple accounts (savings,
>    checking, business). Our schema could evolve to support that by simply
>    removing the UNIQUE constraint on `user_id`.
> 3. **Cleaner JOINs**: Transaction queries only need the accounts table,
>    not the full users table with password hashes.
>
> The `user_id UNIQUE` constraint enforces 1:1 for now while keeping the design clean.

**Q: Why DECIMAL(15,2) and not FLOAT for money?**
> FLOAT uses binary floating-point, which cannot represent some decimal fractions exactly:
> ```
> FLOAT:   0.1 + 0.2 = 0.30000000000000004  (WRONG)
> DECIMAL: 0.1 + 0.2 = 0.30                 (CORRECT)
> ```
> For financial applications, even a 1 paisa (₹0.01) error is unacceptable.
> DECIMAL stores exact decimal values with no rounding errors.
>
> `DECIMAL(15, 2)` means: up to 15 total digits, 2 after the decimal point.
> Max value: 9,999,999,999,999.99 — more than enough for a wallet system.

**Q: What does `CHECK (balance >= 0)` do? Why not just check in the app?**
> This is **defense-in-depth** — validating at BOTH the application and database levels.
>
> The app checks balance before a withdrawal, but what if:
> - A bug in the code skips the check?
> - Two concurrent requests pass the check simultaneously? (race condition)
> - Someone modifies the database directly via SQL?
>
> The CHECK constraint is the **last line of defense**. If anything tries to set
> balance below zero, the database itself rejects it:
> ```
> ERROR 3819: Check constraint 'chk_balance_non_negative' is violated.
> ```
> We tested this and confirmed it works.

**Q: What does `ON DELETE RESTRICT` mean?**
> It prevents deleting a user who has an account. If you try:
> ```sql
> DELETE FROM users WHERE id = 2;
> ```
> MySQL responds:
> ```
> ERROR 1451: Cannot delete or update a parent row: foreign key constraint fails
> ```
> This prevents **orphaned records** — an account with no owner would be a data
> integrity problem. You must handle the account first (close it, transfer funds).

**Q: What is an account_number and why auto-generate it?**
> Account numbers (ACC00001, ACC00002, ...) are human-readable identifiers.
> In real banking, this is what appears on statements and transfer forms.
> We generate it from the user ID: `ACC{user_id:05d}` — simple, unique, predictable.

---

### TABLE: `transactions`

```sql
CREATE TABLE transactions (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    transaction_ref     VARCHAR(36) NOT NULL UNIQUE,
    from_account_id     INT DEFAULT NULL,
    to_account_id       INT DEFAULT NULL,
    transaction_type    ENUM('deposit', 'withdrawal', 'transfer') NOT NULL,
    amount              DECIMAL(15, 2) NOT NULL,
    status              ENUM('success', 'failed') NOT NULL DEFAULT 'success',
    description         VARCHAR(255) DEFAULT NULL,
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ...
    CONSTRAINT chk_amount_positive CHECK (amount > 0)
) ENGINE=InnoDB;
```

**Q: How do you model deposits, withdrawals, and transfers in one table?**
> By using nullable `from_account_id` and `to_account_id`:
>
> | Type | from_account_id | to_account_id | Meaning |
> |---|---|---|---|
> | deposit | NULL | receiver | Money comes from "outside" the system |
> | withdrawal | sender | NULL | Money goes "outside" the system |
> | transfer | sender | receiver | Money moves between two accounts |
>
> NULL means "external" — outside our system. This is the **single-entry** model:
> one row per transaction regardless of type.

**Q: What's the alternative to single-entry? Why didn't you use it?**
> The alternative is **double-entry bookkeeping**: every transfer creates TWO rows:
> - Row 1: debit (money leaves sender)
> - Row 2: credit (money arrives at receiver)
>
> Double-entry is used in real accounting systems for mathematical verification
> (sum of debits = sum of credits). But for a mini wallet system, it's over-engineering.
> Single-entry is simpler, easier to query, and sufficient for our needs.

**Q: Why `transaction_ref` (UUID) in addition to the `id`?**
> Auto-increment IDs are sequential: if a user sees `txn_id=100`, they know `txn_id=99`
> and `txn_id=101` exist. This is **information leakage**.
>
> UUIDs are random and unpredictable — safe to show in URLs, receipts, and APIs.
> In real payment systems, this is the reference number given to customers.
>
> We keep `id` (auto-increment) as the internal primary key because:
> - JOINs are faster on integers than strings
> - Auto-increment is simpler for the database engine

**Q: Why `CHECK (amount > 0)` and not `>= 0`?**
> A transaction of ₹0.00 makes no sense — it's a no-op. Preventing zero amounts
> eliminates a class of bugs and edge cases. The direction of money flow is
> determined by `from_account_id` / `to_account_id`, not by the sign of the amount.

**Q: Why record FAILED transactions instead of just not inserting them?**
> Audit trail. In a real financial system, you need to know:
> - How many failed transfers happened?
> - Is someone repeatedly trying to overdraw their account?
> - Are there patterns of fraud?
> Failed records are evidence. Deleting them destroys evidence.

**Q: What are the indexes for?**
> ```sql
> CREATE INDEX idx_txn_from_account ON transactions(from_account_id);
> CREATE INDEX idx_txn_to_account   ON transactions(to_account_id);
> CREATE INDEX idx_txn_created_at   ON transactions(created_at);
> CREATE INDEX idx_txn_type         ON transactions(transaction_type);
> ```
> Without indexes, MySQL scans EVERY row (full table scan) — O(n).
> With indexes, it jumps directly to matching rows — O(log n).
>
> - `idx_txn_from_account`: "Show me all transactions SENT BY account X" (history page)
> - `idx_txn_to_account`: "Show me all transactions RECEIVED BY account X"
> - `idx_txn_created_at`: "Show me transactions from TODAY" (daily limit check)
> - `idx_txn_type`: "Show me all deposits" (admin filter)
>
> **Why not index every column?** Indexes speed up reads but slow down writes
> (every INSERT/UPDATE must also update the index). Only index columns used in
> WHERE, JOIN, or ORDER BY clauses of frequent queries.

---

### TABLE: `audit_logs`

```sql
CREATE TABLE audit_logs (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    user_id         INT DEFAULT NULL,
    action          VARCHAR(100) NOT NULL,
    details         TEXT DEFAULT NULL,
    ip_address      VARCHAR(45) DEFAULT NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_audit_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB;
```

**Q: Why is `user_id` nullable?**
> Some events don't have a user — for example, a failed login attempt with a
> username that doesn't exist in the system. There's no user to link to, but
> we still want to record that someone tried.

**Q: Why `VARCHAR(100)` for action instead of ENUM?**
> New event types may be added as features grow (password change, profile update,
> API calls, etc.). With ENUM, each new type requires `ALTER TABLE` which can be
> slow on large tables and requires a migration. VARCHAR is more flexible for
> a column where new values are expected.

**Q: Why `VARCHAR(45)` for IP address?**
> IPv4 addresses are up to 15 chars: `"255.255.255.255"`
> IPv6 addresses are up to 39 chars: `"2001:0db8:85a3:0000:0000:8a2e:0370:7334"`
> IPv4-mapped IPv6 can be up to 45 chars: `"::ffff:255.255.255.255"`
> VARCHAR(45) covers all formats.

**Q: Why a separate audit_logs table instead of adding a `last_login` column to users?**
> `last_login` only tells you the MOST RECENT login. Audit logs tell you:
> - Every login (successful and failed)
> - From which IP address
> - At what time
> - What actions were taken
> This is required for compliance (PCI-DSS, SOX) in real financial systems.

---

## Cross-Table Design Questions

**Q: Why InnoDB and not MyISAM?**
> InnoDB supports:
> - **Foreign keys** (MyISAM does NOT)
> - **Transactions** with BEGIN / COMMIT / ROLLBACK (MyISAM does NOT)
> - **Row-level locking** (MyISAM uses table-level locking = worse concurrency)
> - **ACID compliance** (Atomicity, Consistency, Isolation, Durability)
>
> For a financial system, InnoDB is the ONLY option. A transfer that debits one
> account but crashes before crediting the other would corrupt data with MyISAM.

**Q: What is normalization? Is this schema normalized?**
> Normalization eliminates data redundancy:
> - **1NF**: Each column has atomic values (no lists). ✅
> - **2NF**: No partial dependencies (every non-key column depends on the full PK). ✅
> - **3NF**: No transitive dependencies (non-key columns don't depend on other non-key columns). ✅
>
> Example: We don't store the sender's username in the transactions table —
> we store `from_account_id` and JOIN to get the username. This avoids data
> getting out of sync (what if the user changes their username?).

**Q: What is referential integrity and how does this schema enforce it?**
> Referential integrity means every foreign key points to an existing record.
> - `accounts.user_id` → must exist in `users.id`
> - `transactions.from_account_id` → must exist in `accounts.id`
> - `transactions.to_account_id` → must exist in `accounts.id`
> - `audit_logs.user_id` → must exist in `users.id`
>
> If you try to insert a transaction with `from_account_id = 999` and account 999
> doesn't exist, MySQL rejects it. This prevents "ghost" references.

**Q: Why `TIMESTAMP` and not `DATETIME`?**
> TIMESTAMP stores values in UTC internally and converts to the session timezone
> on retrieval. This is ideal for servers in different timezones.
> DATETIME stores the value as-is with no timezone conversion.
> For a consistent audit trail, TIMESTAMP is the safer choice.

---

## Seed Data Design Decisions

**Q: Why pre-compute password hashes in seed.sql instead of storing plaintext?**
> Even in development, we demonstrate security best practices. The seed file shows
> that passwords are NEVER stored as plaintext — they go through Werkzeug's
> `generate_password_hash()` before insertion. If someone reads seed.sql,
> they see hash strings, not passwords.

**Q: Why create a "locked" test user (bob)?**
> To test edge cases without manually triggering them:
> - Can a locked user log in? (should be blocked)
> - Can an admin unlock them?
> - Does the account show "suspended" status?
> Having pre-built test scenarios saves development time.

**Q: Why include sample transactions and audit logs in the seed?**
> So the transaction history page and admin dashboard aren't empty during development.
> It's much easier to build and debug UI when there's realistic data to display.

---

## Constraint Verification (Tested and Proved)

### CHECK constraint blocks negative balance:
```sql
UPDATE accounts SET balance = -100 WHERE id = 1;
-- ERROR 3819: Check constraint 'chk_balance_non_negative' is violated.
```

### FK constraint blocks orphan deletion:
```sql
DELETE FROM users WHERE id = 2;
-- ERROR 1451: Cannot delete or update a parent row: foreign key constraint fails
```

These proofs show the database enforces business rules independently of the application code.
