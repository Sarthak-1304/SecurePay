# SecurePay — Secure Digital Wallet Simulation System

> **A concurrency-hardened, ACID-compliant digital wallet simulation engine built with Python (Flask) and MySQL (InnoDB).**  
> *Engineered to demonstrate database transaction management, pessimistic row-level locking, deadlock prevention, role-based access control (RBAC), and security compliance logging.*

---

## 📌 Project Overview & Disclaimer

**SecurePay** is an educational, production-patterned simulation of a digital wallet platform. It is engineered from first principles without heavy ORMs to demonstrate fundamental software engineering and database concepts:
- **ACID Transaction Lifecycle**: Two-phase atomic debit/credit operations with strict `COMMIT` / `ROLLBACK` guarantees.
- **Concurrency & Race Condition Defenses**: Pessimistic row-level locking (`SELECT ... FOR UPDATE`) preventing the classic Double-Spending anomaly.
- **Deadlock-Free Transfers**: Deterministic numerical lock ordering mathematically eliminating circular wait states.
- **Defense-in-Depth Security**: Werkzeug `scrypt` password hashing, automated 5-attempt brute-force lockouts, session cookie hardening (`HTTPOnly`, `SameSite`), and zero PII leakage in audit trails.
- **Role-Based Access Control (RBAC)**: Backend decorator protection (`@admin_required`) for administrative operations.

> **⚠️ Disclaimer**: This project is designed as an educational, interview-ready demonstration of backend concurrency and transaction architecture. It is not an actual licensed banking application or payment gateway.

---

## 🎯 Problem Statement

Building reliable financial systems requires addressing several classic software and database challenges:
1. **The Double-Spending Anomaly**: Two simultaneous withdrawal requests spending the same balance concurrently.
2. **The Distributed Deadlock Hazard**: Concurrent bidirectional transfers (User A $\rightarrow$ User B while User B $\rightarrow$ User A) causing circular wait deadlocks.
3. **Partial Transfer Corruption**: A server crash or network drop occurring after deducting money from the sender but before crediting the receiver.
4. **Brute-Force Credential Stuffing**: Automated dictionary attacks on authentication endpoints.
5. **Insecure Direct Object References (IDOR)**: Malicious users manipulating request parameters to view or mutate another user's balance.

SecurePay solves all five challenges through rigorous backend validation, pessimistic locking, and relational database constraints.

---

## 🛠️ Technology Stack

| Layer | Technology | Rationale |
|---|---|---|
| **Backend Framework** | **Python 3.10+ / Flask** | Lightweight, transparent HTTP routing without heavy magic |
| **Database Engine** | **MySQL 8.0+ (InnoDB Engine)** | Strict ACID compliance, row-level locking, foreign keys |
| **Database Driver** | **`mysql-connector-python`** | Direct parameterized SQL queries; zero ORM abstraction overhead |
| **Cryptography** | **Werkzeug Security (`scrypt`)** | Memory-hard, salted password hashing |
| **Frontend UI** | **Jinja2 + Bootstrap 5 CDN** | Clean, accessible, minimal JavaScript interface |
| **Configuration** | **`python-dotenv`** | 12-Factor App secret management via environment variables |
| **Testing** | **Python `unittest` & `threading`** | 35 automated test cases including multi-threaded concurrency tests |

---

## 🏛️ System Architecture & Request Lifecycle

```text
 Client Browser (HTTP Request)
        │
        ▼
 Flask Routing & Decorators
 ├── @login_required (Verifies session['user_id'])
 └── @admin_required (Verifies session['role'] == 'admin')
        │
        ▼
 Business Logic & Sanitization (helpers/validators.py, helpers/audit.py)
        │
        ▼
 MySQL InnoDB Database (Direct Parameterized SQL)
 ├── 1. START TRANSACTION (autocommit=False)
 ├── 2. SELECT ... FOR UPDATE (Pessimistic Row Lock in Sorted ID Order)
 ├── 3. Validate Balance & Daily Limit
 ├── 4. UPDATE accounts (Debit Sender, Credit Receiver)
 ├── 5. INSERT INTO transactions (Immutable Ledger Record)
 ├── 6. INSERT INTO audit_logs (Sanitized Compliance Event)
 └── 7. COMMIT (or ROLLBACK on any failure)
```

---

## 🗄️ Database Schema Design

The database schema is structured into 4 normalized tables in third normal form (3NF):

```text
┌───────────────────────────┐         ┌───────────────────────────┐
│           users           │ 1     1 │         accounts          │
├───────────────────────────┼─────────┼───────────────────────────┤
│ id (PK, INT AUTO_INC)     │◄─────── │ id (PK, INT AUTO_INC)     │
│ username (VARCHAR UNIQUE) │         │ user_id (FK, UNIQUE)      │
│ email (VARCHAR UNIQUE)    │         │ account_number (VARCHAR)  │
│ password_hash (VARCHAR)   │         │ balance (DECIMAL(15,2))   │
│ role (ENUM 'user','admin')│         │ status (ENUM)             │
│ is_locked (BOOLEAN)       │         │ daily_limit (DECIMAL)     │
│ failed_logins (INT)       │         └─────────────┬─────────────┘
└─────────────┬─────────────┘                       │
              │ 1                                   │ 1
              │                                     │
              │ N                                   │ N
┌─────────────▼─────────────┐         ┌─────────────▼─────────────┐
│        audit_logs         │         │       transactions        │
├───────────────────────────┤         ├───────────────────────────┤
│ id (PK, INT AUTO_INC)     │         │ id (PK, INT AUTO_INC)     │
│ user_id (FK, NULLABLE)    │         │ transaction_ref (UUID)    │
│ action (VARCHAR)          │         │ from_account_id (FK)      │
│ details (TEXT)            │         │ to_account_id (FK)        │
│ ip_address (VARCHAR)      │         │ transaction_type (ENUM)   │
│ created_at (TIMESTAMP)    │         │ amount (DECIMAL(15,2))    │
└───────────────────────────┘         │ status (ENUM)             │
                                      │ created_at (TIMESTAMP)    │
                                      └───────────────────────────┘
```

### Key Schema Constraints
- **Exact Monetary Precision**: `balance` and `amount` are `DECIMAL(15, 2)` to eliminate IEEE 754 floating-point rounding errors.
- **Database-Level Invariants**:
  - `CONSTRAINT chk_balance_non_negative CHECK (balance >= 0)`
  - `CONSTRAINT chk_amount_positive CHECK (amount > 0)`
- **Referential Integrity**: `FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT` prevents deleting users with active balances.
- **Query Optimization Indexes**: Indexes on `transactions(from_account_id)`, `transactions(to_account_id)`, and `audit_logs(action, created_at)`.

---

## 🔒 Key Database & Concurrency Concepts

### 1. The Double-Spending Defense (Pessimistic Locking)
When a user requests a withdrawal or transfer, SecurePay locks the account row using:
```sql
SELECT balance, status FROM accounts WHERE user_id = %s FOR UPDATE;
```
If two requests arrive simultaneously:
1. Thread A acquires the exclusive row lock.
2. Thread B is placed in a queue by MySQL InnoDB.
3. Thread A validates the balance, executes the deduction, and commits (releasing the lock).
4. Thread B awakens, reads the *newly updated* lower balance, fails the check, and is safely rejected.

### 2. Deadlock Prevention (Deterministic Lock Ordering)
In peer-to-peer transfers involving two accounts ($A$ and $B$), locking without order causes a circular wait if $A \rightarrow B$ and $B \rightarrow A$ occur simultaneously.

**SecurePay Solution**: We sort account IDs numerically before acquiring locks:
```python
first_id, second_id = sorted([sender_account_id, receiver_account_id])
cursor.execute(
    "SELECT id, balance FROM accounts WHERE id IN (%s, %s) ORDER BY id FOR UPDATE",
    (first_id, second_id)
)
```
Because all threads acquire locks in the exact same numerical sequence, **circular wait deadlocks are mathematically eliminated**.

### 3. ACID Guarantees in Transfers
- **Atomicity**: Sender deduction and receiver credit occur in a single transaction; failure at any point triggers `ROLLBACK`.
- **Consistency**: Net money in the system is conserved: $\Delta \text{Balance}_A + \Delta \text{Balance}_B = 0$.
- **Isolation**: Row-level locking isolates concurrent transactions from dirty reads or race conditions.
- **Durability**: Upon `COMMIT`, MySQL's Write-Ahead Log (WAL / redo log) persists changes to disk.

---

## 🛡️ Authentication, Security & RBAC

1. **Password Hashing**: Passwords are never stored in plaintext or weak hashes (like MD5 or plain SHA-256). Uses Werkzeug's `generate_password_hash()` utilizing `scrypt` with a cryptographically secure random salt.
2. **Brute-Force Defense**: Tracks consecutive failed logins in `users.failed_logins`. On the 5th failed attempt, the account is automatically locked (`is_locked = TRUE`), its wallet suspended (`status = 'suspended'`), and an `ACCOUNT_LOCKED` event is logged.
3. **Session Cookie Hardening**:
   - `SESSION_COOKIE_HTTPONLY = True`: Blocks JavaScript from reading session cookies (XSS mitigation).
   - `SESSION_COOKIE_SAMESITE = 'Lax'`: Protects against Cross-Site Request Forgery (CSRF).
   - `session.clear()`: Destroys old session data on login/logout to prevent Session Fixation.
4. **IDOR Mitigation**: All user-facing routes query exclusively against the cryptographically signed `session['user_id']`. Form parameters cannot override the actor's identity.
5. **PII Sanitization in Logs**: `helpers/audit.py` sanitizes event strings to ensure plain passwords or tokens never enter `audit_logs`.
6. **Role-Based Access Control (RBAC)**:
   - `user`: Access personal wallet, deposit, withdraw, transfer, and personal ledger.
   - `admin`: Access `/admin/dashboard`, `/admin/users` (with one-click user unlock), `/admin/transactions`, and `/admin/audit-logs`.

---

## 🚀 Setup & Installation Guide

### Prerequisites
- Python 3.10 or higher
- MySQL Server 8.0+ (running locally on port `3306`)
- Git

### 1. Clone the Repository
```powershell
git clone https://github.com/Sarthak-1304/SecurePay.git
cd SecurePay
```

### 2. Create and Activate Virtual Environment
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1   # On Windows
# source venv/bin/activate    # On Linux/macOS
```

### 3. Install Dependencies
```powershell
pip install -r requirements.txt
```

### 4. Database Configuration
1. Open your MySQL client (Command Line, Workbench, or DBeaver).
2. Create the database and seed the schema:
   ```sql
   CREATE DATABASE securepay_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   USE securepay_db;
   SOURCE schema.sql;
   SOURCE seed.sql;
   ```
3. Create your `.env` file from the template:
   ```powershell
   cp .env.example .env
   ```
4. Edit `.env` with your local MySQL credentials:
   ```ini
   SECRET_KEY=your-secure-random-secret-key
   MYSQL_HOST=localhost
   MYSQL_PORT=3306
   MYSQL_USER=root
   MYSQL_PASSWORD=your_mysql_password
   MYSQL_DATABASE=securepay_db
   ```

---

## 🧪 Running the Master Automated Test Suite

SecurePay includes **35 automated test cases** covering authentication, wallet operations, P2P transfers, tenant isolation, admin RBAC, and multi-threaded concurrency.

Run the master test runner:
```powershell
py run_all_tests.py
```

Expected output:
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
======================================================================
```

---

## 💻 Running the Application Locally

Start the Flask development server:
```powershell
py app.py
```
Open your browser and navigate to: **`http://127.0.0.1:5000`**

### Pre-Seeded Demonstration Accounts

| Role | Username | Email | Password | Initial Balance | Initial Status |
|---|---|---|---|---|---|
| **Admin** | `admin` | `admin@securepay.com` | `admin123` | ₹0.00 | Active (`admin`) |
| **User** | `john` | `john@example.com` | `password123` | ₹10,000.00 | Active (`user`) |
| **User** | `jane` | `jane@example.com` | `password123` | ₹5,000.00 | Active (`user`) |
| **User** | `bob` | `bob@example.com` | `password123` | ₹2,500.00 | Suspended / Locked |

---

## 📸 Screenshots Section Placeholder

| Feature | Preview |
|---|---|
| **Landing & Dashboard** | *[Add screenshot of wallet balance, quick actions, and transaction summary]* |
| **P2P Transfer & Daily Limit** | *[Add screenshot of transfer form with real-time daily spending meters]* |
| **Transaction Ledger & Filters** | *[Add screenshot of filterable multi-column transaction history]* |
| **Admin Panel & User Directory** | *[Add screenshot of admin metrics and one-click account unlock table]* |
| **System Security Audit Trail** | *[Add screenshot of compliance audit logs with IP addresses]* |

---

## 🔮 Future Improvements & Roadmap

1. **Two-Factor Authentication (2FA)**: Time-based One-Time Passwords (TOTP via Google Authenticator) for high-value transfers.
2. **Webhook Notifications**: Real-time event notifications for completed peer-to-peer transfers.
3. **Database Connection Pooling**: Integrating `mysql.connector.pooling` for high-throughput connection reuse under production scale.
4. **Idempotency Keys**: Enforcing client-side UUID idempotency tokens in HTTP headers to safeguard against accidental network retries.

---

## 📄 License

This project is open-source and available under the [MIT License](LICENSE).
