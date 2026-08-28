# PHASE 6 — Transaction History, Audit Logging & Compliance
## What Was Done + Interview Defense Guide

---

## What Was Built In This Phase

| File | Purpose |
|---|---|
| `helpers/audit.py` | Centralized, secure audit logging framework (`log_audit_event`) with automatic client IP extraction and sensitive credential sanitization |
| `routes/admin.py` | Administrator oversight blueprint featuring `/admin/dashboard` (platform metrics) and `/admin/audit-logs` (searchable compliance log viewer) |
| `routes/wallet.py` | Enhanced `/history` endpoint with multi-dimensional filtering by type (`deposit`, `withdrawal`, `transfer`), status (`success`, `failed`), date range, and keyword search |
| `templates/wallet/history.html` | Updated transaction ledger UI with date pickers, status dropdown, type tabs, and search bar |
| `templates/admin/dashboard.html` | Administrator dashboard displaying platform totals (users, locked accounts, total deposits, processed ledger transactions) and recent events |
| `templates/admin/audit_logs.html` | Full system audit trail viewer with action filter dropdown, date range filter, and user search |
| `templates/base.html` | Added Admin dropdown menu (Admin Panel & Audit Logs) in navbar for users with `role = 'admin'` |
| `app.py` | Registered `admin_bp` Blueprint |
| `test_audit_history.py` | Automated test suite verifying 4 test scenarios (user isolation, history filters, audit helper sanitization, and admin RBAC) |

---

## Technical Deep-Dive & Interview Defense Guide

---

### 1. Audit Logging Architecture & Regulatory Compliance

**Q: Why do financial systems require audit logging, and how is it implemented in SecurePay?**

> In financial and enterprise systems (PCI-DSS, SOC 2, SOX compliance), every state-changing and security-sensitive action must produce an **immutable, tamper-evident audit record**:
>
> 1. **Authentication Events**: `LOGIN_SUCCESS`, `LOGIN_FAILED`, `LOGOUT`, `REGISTER`.
> 2. **Security Events**: `ACCOUNT_LOCKED`, `LOGIN_BLOCKED`, `PASSWORD_CHANGE`.
> 3. **Financial Events**: `DEPOSIT`, `WITHDRAWAL`, `TRANSFER`.
> 4. **Administrative Actions**: `ADMIN_UNLOCK`, `ADMIN_OVERRIDE`.
>
> In `helpers/audit.py`, `log_audit_event()` records:
> - **WHO**: `user_id` (foreign key to `users.id`, or `NULL` for anonymous attempts).
> - **WHAT**: `action` (e.g. `TRANSFER`) and `details` (human-readable summary).
> - **WHEN**: `created_at` (automatic database `TIMESTAMP` in UTC).
> - **WHERE**: `ip_address` (extracted from `X-Forwarded-For` or `remote_addr`).

---

### 2. Protecting Sensitive Data in Audit Logs (No Password Leakage)

**Q: How do you prevent sensitive credentials from leaking into log files or databases?**

> **The Risk**:
> If a developer logs `f"User attempted login with password {password}"`, plain passwords are stored permanently in audit tables, which violates compliance and creates a major security vulnerability if logs are viewed by operators.
>
> **The Defense in SecurePay**:
> 1. We **never** pass password variables into audit log descriptions.
> 2. `helpers/audit.py` includes a defensive sanitizer:
>    ```python
>    if 'password' in details.lower():
>        details = "[SANITIZED EVENT]: " + details.replace("password", "p***word")
>    ```
> 3. Authentication failures only record the username and attempt counter (e.g. *"Wrong password attempt 2 of 5"*), never the submitted password characters.

---

### 3. Strict User Isolation & Preventing IDOR in Transaction History

**Q: How do you guarantee that a user cannot see someone else's transaction history?**

> In `routes/wallet.py`, the history query is **strictly bound to the authenticated user's wallet**:
> ```sql
> SELECT t.*, ...
> FROM transactions t
> WHERE (t.from_account_id = %s OR t.to_account_id = %s)
> ```
> Where `%s` is exclusively derived from `session['user_id']`.
>
> **Why this matters**:
> Even if an attacker attempts an Insecure Direct Object Reference (IDOR) attack by manipulating query parameters (`?user_id=2` or `?account_id=ACC00001`), the backend ignores request parameters and filters strictly on the verified session ID. We proved this in `test_audit_history.py` (Test 1).

---

### 4. Dynamic Parameterized Query Construction

**Q: How do you implement multi-criteria filtering without risking SQL injection?**

> In `routes/wallet.py` (`/history`) and `routes/admin.py` (`/admin/audit-logs`), SQL queries are assembled dynamically using **safe parameterized clauses**:
>
> ```python
> sql = "SELECT * FROM transactions WHERE (from_account_id = %s OR to_account_id = %s)"
> params = [account_id, account_id]
>
> if filter_type in ['deposit', 'withdrawal', 'transfer']:
>     sql += " AND transaction_type = %s"
>     params.append(filter_type)
>
> if filter_status in ['success', 'failed']:
>     sql += " AND status = %s"
>     params.append(filter_status)
>
> if date_from:
>     sql += " AND DATE(created_at) >= %s"
>     params.append(date_from)
>
> if search_query:
>     sql += " AND (description LIKE %s OR transaction_ref LIKE %s)"
>     wildcard = f"%{search_query}%"
>     params.extend([wildcard, wildcard])
>
> cursor.execute(sql, tuple(params))
> ```
>
> **Key Interview Takeaways**:
> 1. Whitelisting: `filter_type` and `filter_status` are checked against a fixed allow-list before being added.
> 2. Parameterization: All user inputs (`search_query`, `date_from`, `date_to`) are passed via `%s` placeholders, never formatted into raw SQL strings.

---

### 5. Role-Based Access Control (RBAC) on Admin Endpoints

**Q: How is the Admin Audit Log protected against unauthorized users?**

> Using the custom `@admin_required` decorator in `helpers/decorators.py`:
> ```python
> def admin_required(view_function):
>     @wraps(view_function)
>     def decorated_function(*args, **kwargs):
>         if 'user_id' not in session:
>             flash("Please log in to access this page.", "warning")
>             return redirect(url_for('auth.login', next=request.path))
>         if session.get('role') != 'admin':
>             flash("Access denied: Administrator privileges required.", "danger")
>             return redirect(url_for('home'))
>         return view_function(*args, **kwargs)
>     return decorated_function
> ```
> Regular users requesting `/admin/audit-logs` or `/admin/dashboard` are immediately redirected with a 403-equivalent flash message.

---

### 6. Database Indexing Strategy for Fast Log Retrieval

**Q: How is the database optimized for querying millions of audit logs?**

> From `schema.sql`:
> - `CREATE INDEX idx_audit_user ON audit_logs(user_id);` $\rightarrow$ Fast filtering by specific user.
> - `CREATE INDEX idx_audit_action ON audit_logs(action);` $\rightarrow$ Fast category filtering (`WHERE action = 'LOGIN_FAILED'`).
> - `CREATE INDEX idx_audit_created ON audit_logs(created_at);` $\rightarrow$ Fast range queries for date filters (`ORDER BY created_at DESC`).

---

## Automated Test Verification Results (`test_audit_history.py`)

| # | Test Case | Expected Behavior | Result |
|---|---|---|---|
| 1 | **User Data Isolation** | John cannot see Jane's private transactions; users only see transactions involving their wallet. | **PASS** ✅ |
| 2 | **Multi-Dimensional Filters** | Filter ledger by type (`deposit`), status (`success`), date range, and search keyword. | **PASS** ✅ |
| 3 | **Audit Helper & Sanitization** | `log_audit_event()` persists records with IP; automatically sanitizes sensitive password terms. | **PASS** ✅ |
| 4 | **Admin RBAC & Log Viewer** | Regular users are denied access to `/admin/audit-logs`; admins can view and filter all logs. | **PASS** ✅ |
