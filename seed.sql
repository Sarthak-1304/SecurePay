-- =====================================================================
-- seed.sql — Sample data for development and testing
-- =====================================================================
-- Run AFTER schema.sql:
--   mysql -u root -p securepay_db < seed.sql
--
-- PASSWORDS:
--   All passwords below are hashed using Werkzeug's generate_password_hash().
--   They are NOT plaintext. The actual passwords for testing are:
--
--     admin    → admin123
--     john     → password123
--     jane     → password123
--     bob      → password123
--
--   These are ONLY for development. Never use weak passwords in production.
-- =====================================================================


-- =====================================================================
-- SAMPLE USERS
-- =====================================================================
-- We create 4 users to test different scenarios:
--   1. admin  — Admin role, for testing the admin panel
--   2. john   — Normal active user with some balance
--   3. jane   — Normal active user with some balance
--   4. bob    — Locked user (for testing account lock behavior)
-- =====================================================================

INSERT INTO users (username, email, password_hash, full_name, role, is_locked, failed_logins) VALUES
    ('admin', 'admin@securepay.com',
     'scrypt:32768:8:1$vnEVNOh257h1nXiy$52f8d733ef9352b607911a70f8363e020c256d1586600702193d273bf34b2a833debd1ec01562e468197a3449edfeaf160cf97d2684fd60453ba4882ab8c9b9f',
     'System Admin', 'admin', FALSE, 0),

    ('john', 'john@example.com',
     'scrypt:32768:8:1$Vu5tEuNEMgidy39b$0f3d3c7acff6d368eac106aff8c1a7fec0946c18760b08270d3343ad38e351c95356d9bbb9cc9d3dc5d4437541a10bbc381157bae82e513c149feffc788be2ec',
     'John Doe', 'user', FALSE, 0),

    ('jane', 'jane@example.com',
     'scrypt:32768:8:1$5AVISGhnioqLO50m$5f8541e0515b6dc8cb0842fcbd80205ca4c5aa254f0acb0c6ae3c2057aa4d05cae543e23f9f4905c99f31a6466c58b72208dd62574910e55e3228a9f61c4cf9b',
     'Jane Smith', 'user', FALSE, 0),

    ('bob', 'bob@example.com',
     'scrypt:32768:8:1$GteqqfsQjEYvdJ8t$fffe536a8cd1a8c15c82ff3697cd9193ce41f817d38fce2d2a90a85fb06812d0b40aea84eeeb40af14f40dd38930f94f5dbe50080e4b71740cb79feea41032ff',
     'Bob Wilson', 'user', TRUE, 5);


-- =====================================================================
-- SAMPLE ACCOUNTS (wallets)
-- =====================================================================
-- Each user gets one wallet account.
-- Account numbers follow format: ACC + zero-padded user ID
--
--   admin → ACC00001 (balance: 0)      — Admin doesn't need money
--   john  → ACC00002 (balance: 10,000) — Has money to test transfers
--   jane  → ACC00003 (balance: 5,000)  — Has money to test transfers
--   bob   → ACC00004 (balance: 1,000)  — Locked, for testing lock behavior
-- =====================================================================

INSERT INTO accounts (user_id, account_number, balance, status) VALUES
    (1, 'ACC00001',     0.00, 'active'),      -- admin
    (2, 'ACC00002', 10000.00, 'active'),      -- john — has balance for testing
    (3, 'ACC00003',  5000.00, 'active'),      -- jane — has balance for testing
    (4, 'ACC00004',  1000.00, 'suspended');   -- bob  — suspended (locked user)


-- =====================================================================
-- SAMPLE TRANSACTIONS
-- =====================================================================
-- A few sample transactions so the history page isn't empty during dev.
-- These show all 3 transaction types.
--
--   1. John deposited 10,000
--   2. Jane deposited 5,000
--   3. John transferred 500 to Jane (so we can see both sides)
--   4. Jane withdrew 200
--   5. Bob deposited 1,000
-- =====================================================================

INSERT INTO transactions (transaction_ref, from_account_id, to_account_id, transaction_type, amount, status, description) VALUES
    ('a1b2c3d4-e5f6-7890-abcd-111111111111', NULL, 2, 'deposit',    10000.00, 'success', 'Initial deposit'),
    ('a1b2c3d4-e5f6-7890-abcd-222222222222', NULL, 3, 'deposit',     5000.00, 'success', 'Initial deposit'),
    ('a1b2c3d4-e5f6-7890-abcd-333333333333', 2,    3, 'transfer',     500.00, 'success', 'Payment for lunch'),
    ('a1b2c3d4-e5f6-7890-abcd-444444444444', 3, NULL, 'withdrawal',   200.00, 'success', 'ATM withdrawal'),
    ('a1b2c3d4-e5f6-7890-abcd-555555555555', NULL, 4, 'deposit',     1000.00, 'success', 'Initial deposit');


-- =====================================================================
-- SAMPLE AUDIT LOGS
-- =====================================================================
-- Shows what kind of events get logged in a real scenario.
-- =====================================================================

INSERT INTO audit_logs (user_id, action, details, ip_address) VALUES
    (1, 'REGISTER',       'Admin account created via seed',     '127.0.0.1'),
    (2, 'REGISTER',       'User john registered',               '127.0.0.1'),
    (3, 'REGISTER',       'User jane registered',               '127.0.0.1'),
    (4, 'REGISTER',       'User bob registered',                '127.0.0.1'),
    (2, 'LOGIN_SUCCESS',  'User john logged in',                '127.0.0.1'),
    (2, 'DEPOSIT',        'Deposited 10000.00 to ACC00002',     '127.0.0.1'),
    (3, 'LOGIN_SUCCESS',  'User jane logged in',                '127.0.0.1'),
    (3, 'DEPOSIT',        'Deposited 5000.00 to ACC00003',      '127.0.0.1'),
    (2, 'TRANSFER',       'Transferred 500.00 from ACC00002 to ACC00003', '127.0.0.1'),
    (3, 'WITHDRAWAL',     'Withdrew 200.00 from ACC00003',      '127.0.0.1'),
    (4, 'LOGIN_FAILED',   'Wrong password attempt 1',           '192.168.1.50'),
    (4, 'LOGIN_FAILED',   'Wrong password attempt 2',           '192.168.1.50'),
    (4, 'LOGIN_FAILED',   'Wrong password attempt 3',           '192.168.1.50'),
    (4, 'LOGIN_FAILED',   'Wrong password attempt 4',           '192.168.1.50'),
    (4, 'LOGIN_FAILED',   'Wrong password attempt 5',           '192.168.1.50'),
    (4, 'ACCOUNT_LOCKED', 'Account locked after 5 failed attempts', '192.168.1.50');


-- =====================================================================
-- VERIFICATION QUERIES (run these to check seed data)
-- =====================================================================
-- SELECT u.username, u.role, u.is_locked, a.account_number, a.balance, a.status
--   FROM users u JOIN accounts a ON u.id = a.user_id;
--
-- SELECT transaction_ref, transaction_type, amount, status, description
--   FROM transactions ORDER BY created_at;
--
-- SELECT u.username, al.action, al.details
--   FROM audit_logs al LEFT JOIN users u ON al.user_id = u.id
--   ORDER BY al.created_at;
-- =====================================================================
