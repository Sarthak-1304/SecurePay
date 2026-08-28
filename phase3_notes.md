# PHASE 3 — Authentication & Session Management
## What Was Done + Interview Defense Guide

---

## What Was Built In This Phase

| File | Purpose |
|---|---|
| `helpers/validators.py` | Server-side validation for registration (username regex, email format, password length, match) |
| `helpers/decorators.py` | `@login_required` (AuthN) and `@admin_required` (AuthZ) route protection decorators |
| `routes/auth.py` | Flask Blueprint with `/register`, `/login`, `/logout` endpoints, Werkzeug hashing, failed login counting, and auto-locking |
| `templates/auth/register.html` | User registration page with clean Bootstrap form and feedback styling |
| `templates/auth/login.html` | User login page with demo credentials helper |
| `templates/base.html` | Updated navbar with dynamic auth status (Logout / User badge / Login / Register) |
| `templates/home.html` | Updated hero buttons reflecting session login state |
| `app.py` | Registered `auth_bp` Blueprint |
| `test_auth.py` | Automated test suite verifying all 7 test cases (100% pass rate) |

---

## Core Security Concepts for Interviews

---

### 1. Password Hashing (Werkzeug `scrypt` / `PBKDF2`)

**Q: How do you store passwords and why?**
> We NEVER store plaintext passwords. In `routes/auth.py`, we use:
> ```python
> from werkzeug.security import generate_password_hash, check_password_hash
> password_hash = generate_password_hash(password)
> ```
> This creates a hash string using `scrypt` (or `PBKDF2-HMAC-SHA256`) with a cryptographically secure random salt.

**Q: Why is plain SHA-256 or MD5 dangerous for passwords?**
> 1. **Too fast**: Modern GPUs can compute billions of SHA-256 hashes per second, making brute-force trivial.
> 2. **No built-in salt**: Without unique salts, attackers pre-compute "Rainbow Tables" of known password hashes.
> 3. **Identical hashes**: If two users have the same password, plain SHA-256 produces identical hashes, exposing shared passwords.
>
> Werkzeug uses **key derivation functions** (`scrypt` / `PBKDF2`) designed to be computationally heavy and memory-hard, making brute-force attacks infeasible.

**Q: How does `check_password_hash(stored_hash, submitted_password)` work?**
> It extracts the salt and algorithm parameters embedded in `stored_hash`, hashes `submitted_password` using the same salt, and performs a **constant-time string comparison** (`hmac.compare_digest`) to prevent timing attacks.

---

### 2. Session Management

**Q: How does Flask handle sessions?**
> Flask uses **cryptographically signed client-side cookies**.
> - When a user logs in, we store `session['user_id'] = user['id']`.
> - Flask serializes the session dictionary, signs it using `Config.SECRET_KEY` (via HMAC-SHA1/SHA256), and sends it to the browser as a `session` cookie.
> - On subsequent requests, Flask verifies the HMAC signature. If a malicious user tampers with the cookie, the signature check fails and Flask discards the session.

**Q: How do we prevent Session Fixation attacks?**
> On successful login, we call:
> ```python
> session.clear()
> ```
> before setting new session values. This purges any pre-existing session tokens or residual data from previous sessions.

---

### 3. Authentication vs. Authorization

**Q: What is the difference between Authentication (AuthN) and Authorization (AuthZ)?**
> | Concept | Question Answered | Implementation in SecurePay |
> |---|---|---|
> | **Authentication (AuthN)** | *"Who are you?"* | `/login` verifies credentials; `@login_required` checks `user_id in session` |
> | **Authorization (AuthZ)** | *"What are you allowed to do?"* | `@admin_required` checks `session.get('role') == 'admin'` |

**Q: How does the `@login_required` decorator work under the hood?**
> ```python
> def login_required(view_function):
>     @wraps(view_function)
>     def decorated_function(*args, **kwargs):
>         if 'user_id' not in session:
>             flash("Please log in to access this page.", "warning")
>             return redirect(url_for('auth.login', next=request.path))
>         return view_function(*args, **kwargs)
>     return decorated_function
> ```
> It wraps the target route. If `'user_id'` is absent from `session`, it redirects the user to the login page and preserves the intended destination in `next=request.path`.
> `functools.wraps` preserves the original function name and docstrings, preventing Flask endpoint naming collisions.

---

### 4. Failed-Login Tracking & Account Locking

**Q: Why implement account locking?**
> To prevent **online brute-force attacks** (automated password guessing scripts).
>
> **Workflow:**
> 1. Wrong password $\rightarrow$ increment `users.failed_logins` by 1.
> 2. Show warning: *"You have X attempt(s) remaining."*
> 3. If `failed_logins >= 5`:
>    - Set `users.is_locked = TRUE`
>    - Set `accounts.status = 'suspended'`
>    - Record `ACCOUNT_LOCKED` in `audit_logs`
>    - All future login attempts are blocked immediately with an error message.
> 4. When the user successfully logs in with the correct password, `failed_logins` is reset to 0.

**Q: Why use generic login error messages?**
> When a user does not exist or enters the wrong password, we return:
> *"Invalid username/email or password."*
> We do NOT say *"User does not exist"*. This prevents **Username Enumeration**, where attackers test email lists to see who has an account on the platform.

---

### 5. Atomic Account & Wallet Creation (Database Transactions)

**Q: What happens during registration?**
> When a user registers, two records MUST be created:
> 1. A row in `users` (auth credentials).
> 2. A row in `accounts` (initial wallet with ₹0.00 balance and generated `account_number`).
>
> ```python
> conn = get_db_connection()
> cursor = conn.cursor()
> try:
>     cursor.execute("INSERT INTO users ...")
>     user_id = cursor.lastrowid
>     cursor.execute("INSERT INTO accounts ...", (user_id, f"ACC{user_id:05d}", ...))
>     cursor.execute("INSERT INTO audit_logs ...")
>     conn.commit()  # Both succeed together
> except Exception:
>     conn.rollback()  # If either fails, nothing is saved
> ```
> **Atomicity (ACID)** ensures that we never end up with an orphaned user who has no wallet account, or a wallet with no owner.

---

### 6. Protection Against SQL Injection

**Q: How does this codebase prevent SQL Injection?**
> Every single database query uses **parameterized placeholders (`%s`)**:
> ```python
> # SAFE (Parameterized):
> cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
>
> # DANGEROUS (NEVER DO THIS):
> cursor.execute(f"SELECT * FROM users WHERE username = '{username}'")
> ```
> In parameterized queries, MySQL treats user input strictly as literal data values, never as executable SQL commands, neutralizing SQL injection completely.

---

## Automated Test Verification Results

All 7 core test scenarios were verified using `test_auth.py`:

| # | Test Case | Expected Behavior | Result |
|---|---|---|---|
| 1 | **Successful Registration** | User inserted, password hashed, wallet `ACC0000X` created, `REGISTER` logged in `audit_logs`. | **PASS** ✅ |
| 2 | **Duplicate Registration** | Rejects duplicate username or email with clear error. | **PASS** ✅ |
| 3 | **Successful Login** | Checks hash, creates session (`user_id`, `username`, `role`), logs `LOGIN_SUCCESS`. | **PASS** ✅ |
| 4 | **Wrong Password** | Increments `failed_logins` to 1, flashes warning message. | **PASS** ✅ |
| 5 | **Multiple Failed Attempts** | Tracks consecutive failures ($1 \rightarrow 2 \rightarrow 3 \rightarrow 4 \rightarrow 5$). | **PASS** ✅ |
| 6 | **Account Locking** | On 5th failure: sets `is_locked = TRUE`, suspends wallet, blocks all future logins. | **PASS** ✅ |
| 7 | **Reset on Success & Logout** | Successful login resets counter to 0; `/logout` clears session. | **PASS** ✅ |
