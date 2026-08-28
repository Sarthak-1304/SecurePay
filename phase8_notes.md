# PHASE 8 — Security, Concurrency & Data-Integrity Review
## Complete System Audit & Interview Defense Guide

---

## 21-Point Security & Data-Integrity Audit Matrix

| # | Checkpoint | Verification & Implementation in SecurePay | Status |
|---|---|---|---|
| 1 | **SQL Injection Prevention** | 100% of database queries use parameterized placeholders (`%s`). Zero raw string formatting (`f""`). | **SECURE** ✅ |
| 2 | **Parameterized Queries** | Dynamic filters in `/history` and `/admin/audit-logs` construct safe parameterized tuples. | **SECURE** ✅ |
| 3 | **Password Storage** | Werkzeug `generate_password_hash` (`scrypt`/`PBKDF2` + random salt). Plaintext passwords NEVER stored. | **SECURE** ✅ |
| 4 | **Session Security** | Cryptographically signed cookies. `session.clear()` prevents Session Fixation. Configured `SESSION_COOKIE_HTTPONLY=True` and `SESSION_COOKIE_SAMESITE='Lax'`. | **SECURE** ✅ |
| 5 | **Authentication (AuthN)** | `@login_required` decorator checks `user_id in session`. Unauthenticated requests redirect to login. | **SECURE** ✅ |
| 6 | **Admin Authorization (AuthZ)** | `@admin_required` checks `role == 'admin'`. Regular users requesting `/admin/*` receive Access Denied. | **SECURE** ✅ |
| 7 | **Account Ownership / IDOR** | Wallet queries strictly bind to `session['user_id']`. Form parameters never dictate source account. | **SECURE** ✅ |
| 8 | **Negative/Zero Amount Defense** | `parse_and_validate_amount()` validates `amount > 0` and max 2 decimals. DB has `CHECK (amount > 0)`. | **SECURE** ✅ |
| 9 | **Insufficient Balance Defense** | `balance >= amount` verified under row lock before deducting funds. Overdrafts blocked. | **SECURE** ✅ |
| 10 | **Concurrent Transactions** | `SELECT ... FOR UPDATE` acquires row-level locks on `accounts`. | **SECURE** ✅ |
| 11 | **Race Conditions / Double-Spend** | Pessimistic locking blocks simultaneous withdrawals from spending the same balance twice. | **SECURE** ✅ |
| 12 | **Deadlock Prevention** | Bidirectional transfers sort account IDs (`sorted([A, B])`) to lock rows in deterministic numerical order. | **SECURE** ✅ |
| 13 | **Transaction Rollback** | Every database operation wraps in `try...except` with `conn.rollback()` ensuring zero partial state. | **SECURE** ✅ |
| 14 | **Failed-Login Tracking** | `users.failed_logins` tracks consecutive failed attempts; resets to 0 on successful authentication. | **SECURE** ✅ |
| 15 | **Brute-Force Account Locking** | Automatically sets `is_locked = TRUE` and `status = 'suspended'` on 5th failed login attempt. | **SECURE** ✅ |
| 16 | **Sensitive Data in Logs** | `helpers/audit.py` sanitizes descriptions; passwords and auth tokens NEVER enter `audit_logs`. | **SECURE** ✅ |
| 17 | **Hardcoded Secrets** | `SECRET_KEY` and MySQL credentials stored in `.env` (gitignored). `.env.example` committed. | **SECURE** ✅ |
| 18 | **Environment Variables** | `python-dotenv` loads configuration in `config.py` following 12-Factor App methodology. | **SECURE** ✅ |
| 19 | **Database Constraints** | `CHECK (balance >= 0)`, `CHECK (amount > 0)`, `UNIQUE (username, email, account_number, txn_ref)`. | **SECURE** ✅ |
| 20 | **Foreign Keys & Integrity** | `ON DELETE RESTRICT` on `accounts.user_id` prevents deleting users who have active balances. | **SECURE** ✅ |
| 21 | **Money Representation** | Exact `Decimal` in Python and `DECIMAL(15, 2)` in MySQL — zero binary floating-point rounding errors. | **SECURE** ✅ |

---

## Security Issues Found & Fixes Made in Phase 8

1. **Session Cookie Security Flags**:
   - *Issue*: Session cookies lacked explicit `HTTPOnly` and `SameSite` configurations in `config.py`.
   - *Fix*: Configured `SESSION_COOKIE_HTTPONLY = True` (blocks malicious JavaScript from reading session cookies in XSS scenarios) and `SESSION_COOKIE_SAMESITE = 'Lax'` (mitigates Cross-Site Request Forgery / CSRF).
2. **Payload Size Bounds**:
   - *Issue*: Default HTTP server configuration could accept arbitrary request payloads.
   - *Fix*: Configured `MAX_CONTENT_LENGTH = 16MB` in `config.py` to prevent memory exhaustion Denial of Service (DoS).
3. **Defensive Input Length Capping**:
   - *Issue*: Transaction descriptions from form inputs were unbounded.
   - *Fix*: Defensively capped user note inputs at 255 characters (`description[:255]`) in `deposit`, `withdraw`, and `transfer` before sending to the database.

---

## Top Interview Questions & How to Defend Your Code

---

### 1. SQL Injection & Parameterized Queries
**Q: How does SecurePay prevent SQL Injection?**
> *"Every query in SecurePay is parameterized using `%s` placeholders. When MySQL receives a parameterized query, it compiles the SQL command structure first, and treats user inputs strictly as literal values. Even if a user inputs `' OR 1=1 --`, it is treated as a plain text string rather than executable SQL syntax."*

---

### 2. Password Hashing vs Encryption
**Q: What is the difference between Hashing and Encryption? Why use Werkzeug?**
> *"Encryption is a two-way function (ciphertext can be decrypted back to plaintext with a key). Hashing is a one-way mathematical function (you cannot reverse a hash back to the password).*
> 
> *Werkzeug uses **scrypt / PBKDF2** with a cryptographically secure random salt. This makes brute-forcing computationally expensive and memory-hard, while random salts neutralize Rainbow Table attacks."*

---

### 3. Concurrency & Race Conditions (The Double-Spending Attack)
**Q: What happens if a user submits two simultaneous transfers of ₹1,000 when their balance is only ₹1,000?**
> *"Without locking, both requests read ₹1,000, pass the balance check simultaneously, and deduct ₹2,000 (a Race Condition). In SecurePay, we use **Pessimistic Row-Level Locking (`SELECT ... FOR UPDATE`)**:*
> 1. *Request A locks the account row.*
> 2. *Request B is blocked by MySQL until Request A completes.*
> 3. *Request A deducts ₹1,000, updates balance to ₹0, and commits.*
> 4. *Request B unblocks, reads the new balance (₹0), fails the balance check, and is rejected with 'Insufficient balance'."*

---

### 4. Deadlock Prevention in Transfers
**Q: What is a Database Deadlock and how did you prevent it?**
> *"If User A transfers to User B while User B simultaneously transfers to User A, Thread 1 locks Account A and waits for Account B, while Thread 2 locks Account B and waits for Account A (Circular Wait).*
> 
> *We prevent this using **Deterministic Lock Ordering**: we always sort the account IDs (`sorted([sender_id, receiver_id])`) and acquire row locks in ascending numerical order (`ORDER BY id FOR UPDATE`). Since both threads attempt to lock the lower ID first, circular wait is mathematically impossible."*

---

### 5. Authentication vs Authorization & IDOR
**Q: What is IDOR and how did you prevent it?**
> *"Insecure Direct Object Reference (IDOR) happens when an application trusts user-supplied IDs (e.g. `<input name="account_id" value="2">`). An attacker can change that ID to debit someone else's wallet.*
> 
> *In SecurePay, we **never** accept account or user IDs from form parameters. All financial operations bind strictly to `session['user_id']` verified by our `@login_required` decorator on the backend."*

---

### 6. Defense-in-Depth
**Q: What is Defense-in-Depth in database architecture?**
> *"Defense-in-Depth means validating rules at multiple architectural layers so that a failure in one layer is caught by the next:*
> - *Layer 1 (Frontend HTML/JS)*: `min="0.01"`, required fields.
> - *Layer 2 (Backend Python)*: `parse_and_validate_amount()`, balance checks, daily limit checks.
> - *Layer 3 (Database Schema)*: `CHECK (balance >= 0)`, `CHECK (amount > 0)`, `UNIQUE`, `NOT NULL`, `FOREIGN KEY ON DELETE RESTRICT`.*
> 
> *Even if application code had a bug, MySQL itself rejects invalid states."*
