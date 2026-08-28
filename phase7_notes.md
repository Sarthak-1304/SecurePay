# PHASE 7 — Administrator Dashboard & Role-Based Access Control (RBAC)
## What Was Done + Interview Defense Guide

---

## What Was Built In This Phase

| File | Purpose |
|---|---|
| `routes/admin.py` | Complete administrator oversight blueprint with RBAC enforcement (`@admin_required`), platform KPI metrics, user management, lock/unlock toggle, global transaction monitoring, and audit log viewer |
| `templates/admin/dashboard.html` | Administrator dashboard featuring platform KPI stat cards (active users, locked accounts, total deposits, ledger volume) and quick navigation cards |
| `templates/admin/users.html` | User directory table displaying full user profiles, wallet account numbers, balances, lock status badges, failed login counts, and single-click Lock/Unlock action forms |
| `templates/admin/transactions.html` | Global transaction monitoring table displaying all platform deposits, withdrawals, and transfers with counterparty tracking and type/status filters |
| `templates/base.html` | Updated Admin navbar dropdown menu (`Admin Panel`, `Manage Users`, `All Transactions`, `Security Audit Logs`) |
| `test_admin.py` | Automated test suite verifying 6 test scenarios (RBAC enforcement, dashboard metrics, user directory, lock/unlock cycle, self-lockout prevention, and global transactions) |

---

## Technical Deep-Dive & Interview Defense Guide

---

### 1. Authentication vs. Authorization (AuthN vs. AuthZ)

**Q: Explain the difference between Authentication and Authorization in SecurePay.**

> | Concept | Question Answered | Implementation in SecurePay |
> |---|---|---|
> | **Authentication (AuthN)** | *"Who are you?"* | `/login` verifies credentials with `check_password_hash()`; `@login_required` checks `user_id in session`. |
> | **Authorization (AuthZ)** | *"What are you permitted to do?"* | `@admin_required` checks if the authenticated user has `session.get('role') == 'admin'`. |

**Interview Key Point**:
> *"Authentication verifies your identity (logging in with credentials). Authorization determines your permissions (deciding whether a logged-in user can access administrative tools or only their own wallet)."*

---

### 2. Role-Based Access Control (RBAC) Architecture

**Q: How does RBAC work in this system?**

> SecurePay defines two discrete roles in the database schema:
> ```sql
> role ENUM('user', 'admin') NOT NULL DEFAULT 'user'
> ```
> 1. **`user`**: Can access their own wallet dashboard, deposit, withdraw, transfer money, and view their personal transaction history.
> 2. **`admin`**: Has full oversight: can view platform metrics, inspect all registered users, lock/unlock accounts, monitor all global transactions, and inspect security audit logs.

---

### 3. Backend Route Protection (Why UI Hiding is NOT Security)

**Q: Why is hiding the Admin button in HTML not enough? How is backend protection enforced?**

> **The Security Flaw (Security through Obscurity)**:
> If you only hide the `<a href="/admin/users">Admin</a>` link in HTML using `{% if session.role == 'admin' %}`, an unauthorized user can simply open DevTools or type `http://localhost:5000/admin/users` directly into the address bar and bypass your security.
>
> **The Backend Solution (`@admin_required`)**:
> Every administrative endpoint in `routes/admin.py` is protected by the `@admin_required` decorator:
>
> ```python
> def admin_required(view_function):
>     @wraps(view_function)
>     def decorated_function(*args, **kwargs):
>         # 1. Verify Authentication
>         if 'user_id' not in session:
>             flash("Please log in to access this page.", "warning")
>             return redirect(url_for('auth.login', next=request.path))
>
>         # 2. Verify Authorization (Role Check)
>         if session.get('role') != 'admin':
>             flash("Access denied: Administrator privileges required.", "danger")
>             return redirect(url_for('home'))
>
>         return view_function(*args, **kwargs)
>     return decorated_function
> ```
> If a regular user sends an HTTP GET/POST to any `/admin/*` route, the backend immediately intercepts the request and denies access before executing any database queries.

---

### 4. Account Lock / Unlock Lifecycle & State Synchronization

**Q: What happens under the hood when an administrator locks or unlocks a user?**

> In `routes/admin.py` (`/admin/users/<id>/toggle-lock`), state changes are synchronized across both `users` and `accounts` tables:
>
> **When Admin UNLOCKS a User:**
> 1. `UPDATE users SET is_locked = FALSE, failed_logins = 0 WHERE id = %s`
>    - Clears the locked flag and resets the consecutive failed attempts counter.
> 2. `UPDATE accounts SET status = 'active' WHERE user_id = %s`
>    - Restores wallet status from `suspended` back to `active`.
> 3. `log_audit_event(admin_id, 'ACCOUNT_UNLOCKED', ...)`
>    - Records compliance log of who performed the unlock.
>
> **When Admin LOCKS a User:**
> 1. `UPDATE users SET is_locked = TRUE WHERE id = %s`
> 2. `UPDATE accounts SET status = 'suspended' WHERE user_id = %s`
> 3. `log_audit_event(admin_id, 'ACCOUNT_LOCKED', ...)`
>
> **The User Experience**:
> - Locked user attempting login $\rightarrow$ Blocked with *"Your account is locked due to repeated failed attempts."*
> - Locked user attempting transfer/deposit $\rightarrow$ Blocked with *"Your account is currently suspended."*

---

### 5. Admin Self-Lockout Prevention Rule

**Q: What safety measure prevents the sole administrator from accidentally locking themselves out?**

> In `toggle_lock()`:
> ```python
> if user_id == session['user_id']:
>     flash("Action blocked: You cannot lock your own administrator account.", "danger")
>     return redirect(url_for('admin.users'))
> ```
> This prevents an administrator from locking their own account, which would leave the platform without any active administrator to unlock accounts.

---

### 6. Administrative Audit Trail (Who Watches the Watchers?)

**Q: How do you track administrator actions?**
> Every time an administrator locks an account, unlocks a user, or accesses sensitive audit logs, an immutable record is created in `audit_logs` with:
> - The administrator's `user_id` and username.
> - The target user's ID and username.
> - Client IP address and UTC timestamp.
>
> This creates an accountable **governance audit trail** necessary for financial compliance.

---

## Automated Test Verification Results (`test_admin.py`)

| # | Test Case | Expected Behavior | Result |
|---|---|---|---|
| 1 | **RBAC Route Protection** | Anonymous and regular users (`role='user'`) are blocked from all `/admin/*` routes with Access Denied. | **PASS** ✅ |
| 2 | **Admin Dashboard** | Admin user (`role='admin'`) accesses dashboard, views platform totals (users, locked, volume). | **PASS** ✅ |
| 3 | **User Directory** | Admin accesses `/admin/users` and views all registered accounts with live balances and lock states. | **PASS** ✅ |
| 4 | **Lock / Unlock Lifecycle** | Lock user Jane $\rightarrow$ wallet suspended $\rightarrow$ login blocked $\rightarrow$ Unlock user Jane $\rightarrow$ wallet active $\rightarrow$ login restored. | **PASS** ✅ |
| 5 | **Self-Lockout Prevention** | Admin attempting to lock their own account is rejected by backend safety check. | **PASS** ✅ |
| 6 | **Global Transactions** | Admin views transactions across all accounts with type and status filtering. | **PASS** ✅ |
