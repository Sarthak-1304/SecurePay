-- =====================================================================
-- SecurePay — Database Schema
-- =====================================================================
--
-- DATABASE DESIGN OVERVIEW
-- ========================
--
-- We have 4 tables:
--
--   1. users          — WHO can use the system (credentials + status)
--   2. accounts       — WHAT they own (wallet with balance)
--   3. transactions   — WHAT happened (every financial operation)
--   4. audit_logs     — WHY / WHEN it happened (security event trail)
--
-- WHY THESE 4 TABLES:
--   users + accounts  → Separated because in real banking, one user can
--                        have multiple accounts (savings, checking, etc.).
--                        Even though we enforce 1:1 here, the schema is
--                        ready to evolve. This is a good interview point.
--
--   transactions      → The HEART of any financial system. We NEVER delete
--                        or update transactions — they are append-only.
--                        This makes the system auditable and trustworthy.
--
--   audit_logs        → Tracks security events (logins, failed attempts,
--                        admin actions). Required for compliance in real
--                        systems. Shows security awareness in interviews.
--
-- TABLE CREATION ORDER MATTERS:
--   Foreign keys require the referenced table to exist first.
--   Order: users → accounts → transactions → audit_logs
--
-- ENGINE = InnoDB is required because it supports:
--   • Foreign keys (MyISAM does NOT)
--   • Transactions with BEGIN / COMMIT / ROLLBACK
--   • Row-level locking (critical for concurrent transfers)
--   • ACID compliance
--
-- =====================================================================


-- =====================================================================
-- TABLE 1: users
-- =====================================================================
-- PURPOSE: Stores login credentials and account status.
--          One row per registered person (including admins).
--
-- KEY DESIGN DECISIONS:
--
--   username VARCHAR(50) UNIQUE
--     → Users log in with this. UNIQUE prevents duplicates.
--       VARCHAR(50) is enough for usernames; longer wastes index space.
--
--   email VARCHAR(100) UNIQUE
--     → For identification. UNIQUE prevents one email = two accounts.
--
--   password_hash VARCHAR(256)
--     → Stores Werkzeug's PBKDF2/scrypt hash, NEVER plaintext.
--       256 chars is enough for any hash format Werkzeug produces.
--       WHY NOT plain SHA-256? SHA-256 is fast = easy to brute-force.
--       Werkzeug uses slow hashing (scrypt/PBKDF2) + salt = secure.
--
--   role ENUM('user', 'admin')
--     → Role-based access control. ENUM restricts to known values
--       at the database level — no "superadmin" or typos possible.
--
--   is_locked BOOLEAN DEFAULT FALSE
--     → When TRUE, login is blocked. Set after too many failed attempts
--       or manually by an admin. Simple but effective security.
--
--   failed_logins INT DEFAULT 0
--     → Counter incremented on each failed login attempt.
--       When it reaches 5 → is_locked = TRUE.
--       Resets to 0 on successful login.
--       WHY a counter instead of a separate table?
--       Simpler, and audit_logs already records each event with timestamps.
--
-- =====================================================================
CREATE TABLE IF NOT EXISTS users (
    id              INT             AUTO_INCREMENT PRIMARY KEY,
    username        VARCHAR(50)     NOT NULL UNIQUE,
    email           VARCHAR(100)    NOT NULL UNIQUE,
    password_hash   VARCHAR(256)    NOT NULL,
    full_name       VARCHAR(100)    NOT NULL,
    role            ENUM('user', 'admin') NOT NULL DEFAULT 'user',
    is_locked       BOOLEAN         NOT NULL DEFAULT FALSE,
    failed_logins   INT             NOT NULL DEFAULT 0,
    created_at      TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;


-- =====================================================================
-- TABLE 2: accounts
-- =====================================================================
-- PURPOSE: Each user's wallet. Holds their balance and spending limits.
--
-- WHY SEPARATE FROM users?
--   In real systems, one person can have multiple accounts (savings,
--   checking, business). Separating them follows proper normalization.
--   Even with our 1:1 constraint, the schema is extensible.
--   This is a GREAT interview talking point about database design.
--
-- KEY DESIGN DECISIONS:
--
--   user_id INT NOT NULL UNIQUE
--     → Foreign key to users(id).
--       UNIQUE enforces ONE account per user (1:1 relationship).
--       NOT NULL means every account must have an owner.
--
--   account_number VARCHAR(20) UNIQUE
--     → Human-readable identifier (e.g., ACC00001).
--       UNIQUE prevents collisions.
--       In real systems, this is what customers see on their statements.
--
--   balance DECIMAL(15, 2) DEFAULT 0.00
--     → WHY DECIMAL, NOT FLOAT?
--       FLOAT has rounding errors: 0.1 + 0.2 = 0.30000000000000004
--       DECIMAL stores exact values: 0.1 + 0.2 = 0.30
--       For money, even a 1 paisa error is unacceptable.
--       DECIMAL(15,2) → up to 9,999,999,999,999.99 (more than enough).
--
--   CHECK (balance >= 0)
--     → DATABASE-LEVEL safety net against negative balances.
--       Even if application code has a bug, the database will reject it.
--       This is defense-in-depth — validate at BOTH app and DB levels.
--
--   daily_limit DECIMAL(15, 2) DEFAULT 50000.00
--     → Maximum outgoing amount (withdrawals + transfers) per day.
--       Checked by the application using SUM() of today's transactions.
--
--   ON DELETE RESTRICT
--     → Prevents deleting a user who has an account.
--       You must delete the account first (or handle it in code).
--       This prevents orphaned financial records.
--
-- =====================================================================
CREATE TABLE IF NOT EXISTS accounts (
    id              INT             AUTO_INCREMENT PRIMARY KEY,
    user_id         INT             NOT NULL UNIQUE,
    account_number  VARCHAR(20)     NOT NULL UNIQUE,
    balance         DECIMAL(15, 2)  NOT NULL DEFAULT 0.00,
    status          ENUM('active', 'suspended', 'closed') NOT NULL DEFAULT 'active',
    daily_limit     DECIMAL(15, 2)  NOT NULL DEFAULT 50000.00,
    created_at      TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_accounts_user
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE RESTRICT,

    CONSTRAINT chk_balance_non_negative
        CHECK (balance >= 0)
) ENGINE=InnoDB;


-- =====================================================================
-- TABLE 3: transactions
-- =====================================================================
-- PURPOSE: Records EVERY financial operation. This is the heart of the system.
--          Transactions are APPEND-ONLY — we never UPDATE or DELETE them.
--          This makes the system auditable and trustworthy.
--
-- HOW THE 3 TRANSACTION TYPES WORK:
--
--   DEPOSIT:     from_account_id = NULL,  to_account_id = receiver
--                Money comes from "outside" (no source account).
--
--   WITHDRAWAL:  from_account_id = sender, to_account_id = NULL
--                Money goes "outside" (no destination account).
--
--   TRANSFER:    from_account_id = sender, to_account_id = receiver
--                Money moves between two accounts in the system.
--                BOTH columns are set.
--
--   This design is called the "single-entry" model — each operation
--   is ONE row. An alternative is "double-entry" (two rows per transfer,
--   one debit + one credit). We use single-entry for simplicity.
--
-- KEY DESIGN DECISIONS:
--
--   transaction_ref VARCHAR(36) UNIQUE
--     → UUID that uniquely identifies each transaction externally.
--       In real payment systems, this is what you'd show on receipts,
--       use in API responses, or give to customer support.
--       Using UUID instead of auto-increment ID prevents information
--       leakage (users can't guess other transaction IDs).
--
--   amount DECIMAL(15, 2) with CHECK (amount > 0)
--     → Amount must always be positive. The direction of money flow
--       is determined by from/to account IDs, not by sign.
--
--   status ENUM('success', 'failed')
--     → Only two outcomes: it either worked or it didn't.
--       Failed transactions are STILL recorded — this is important
--       for auditing and debugging.
--
--   from_account_id / to_account_id — both NULLABLE
--     → NULL means "external" (outside the system).
--       Deposits have no source. Withdrawals have no destination.
--       Both are FK to accounts(id) for referential integrity.
--
-- =====================================================================
CREATE TABLE IF NOT EXISTS transactions (
    id                  INT             AUTO_INCREMENT PRIMARY KEY,
    transaction_ref     VARCHAR(36)     NOT NULL UNIQUE,
    from_account_id     INT             DEFAULT NULL,
    to_account_id       INT             DEFAULT NULL,
    transaction_type    ENUM('deposit', 'withdrawal', 'transfer') NOT NULL,
    amount              DECIMAL(15, 2)  NOT NULL,
    status              ENUM('success', 'failed') NOT NULL DEFAULT 'success',
    description         VARCHAR(255)    DEFAULT NULL,
    created_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_txn_from
        FOREIGN KEY (from_account_id) REFERENCES accounts(id),

    CONSTRAINT fk_txn_to
        FOREIGN KEY (to_account_id) REFERENCES accounts(id),

    CONSTRAINT chk_amount_positive
        CHECK (amount > 0)
) ENGINE=InnoDB;

-- INDEXES: Speed up the most common queries
-- Without indexes, MySQL must scan EVERY row (full table scan).
-- With indexes, it jumps directly to matching rows (like a book index).

-- "Show me all transactions for account X" (transaction history page)
CREATE INDEX idx_txn_from_account ON transactions(from_account_id);
CREATE INDEX idx_txn_to_account   ON transactions(to_account_id);

-- "Show me transactions from today" (daily limit check, admin reports)
CREATE INDEX idx_txn_created_at   ON transactions(created_at);

-- "Show me all deposits" or "Show me all transfers" (filter by type)
CREATE INDEX idx_txn_type         ON transactions(transaction_type);


-- =====================================================================
-- TABLE 4: audit_logs
-- =====================================================================
-- PURPOSE: Security event trail. Records WHO did WHAT and WHEN.
--          In real systems, audit logs are required for compliance
--          (PCI-DSS for payments, SOX for finance, etc.).
--
-- WHAT GETS LOGGED:
--   • LOGIN_SUCCESS    — user logged in
--   • LOGIN_FAILED     — wrong password attempt
--   • ACCOUNT_LOCKED   — account locked after 5 failures
--   • ACCOUNT_UNLOCKED — admin unlocked an account
--   • REGISTER         — new user registered
--   • DEPOSIT          — money deposited
--   • WITHDRAWAL       — money withdrawn
--   • TRANSFER         — money transferred
--   • ADMIN_ACTION     — admin performed an action
--
-- KEY DESIGN DECISIONS:
--
--   user_id INT DEFAULT NULL
--     → NULL for anonymous events (e.g., failed login for a username
--       that doesn't exist — there's no user to link to).
--
--   action VARCHAR(100)
--     → Free-text rather than ENUM because new action types may be
--       added frequently without ALTER TABLE.
--
--   ip_address VARCHAR(45)
--     → Stores the client's IP. VARCHAR(45) supports both:
--       IPv4: "192.168.1.1" (15 chars)
--       IPv6: "2001:0db8:85a3:0000:0000:8a2e:0370:7334" (39 chars)
--
--   No UPDATE or DELETE on this table — audit logs are immutable.
--
-- =====================================================================
CREATE TABLE IF NOT EXISTS audit_logs (
    id              INT             AUTO_INCREMENT PRIMARY KEY,
    user_id         INT             DEFAULT NULL,
    action          VARCHAR(100)    NOT NULL,
    details         TEXT            DEFAULT NULL,
    ip_address      VARCHAR(45)     DEFAULT NULL,
    created_at      TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_audit_user
        FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB;

-- INDEXES for admin panel queries
CREATE INDEX idx_audit_user    ON audit_logs(user_id);
CREATE INDEX idx_audit_action  ON audit_logs(action);
CREATE INDEX idx_audit_created ON audit_logs(created_at);


-- =====================================================================
-- SUMMARY OF ALL CONSTRAINTS
-- =====================================================================
--
-- PRIMARY KEYS:
--   users.id, accounts.id, transactions.id, audit_logs.id
--
-- FOREIGN KEYS:
--   accounts.user_id         → users.id        (ON DELETE RESTRICT)
--   transactions.from_account_id → accounts.id
--   transactions.to_account_id   → accounts.id
--   audit_logs.user_id       → users.id
--
-- UNIQUE:
--   users.username, users.email
--   accounts.user_id, accounts.account_number
--   transactions.transaction_ref
--
-- CHECK:
--   accounts.balance >= 0           (no negative balances)
--   transactions.amount > 0         (no zero/negative amounts)
--
-- NOT NULL:
--   All columns except: from_account_id, to_account_id,
--   description, audit_logs.user_id, audit_logs.details, audit_logs.ip_address
--
-- INDEXES:
--   idx_txn_from_account, idx_txn_to_account, idx_txn_created_at, idx_txn_type
--   idx_audit_user, idx_audit_action, idx_audit_created
--
-- =====================================================================
