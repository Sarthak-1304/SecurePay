# PHASE 1 — Project Setup & Foundation
## What Was Done + Interview Defense Guide

---

## What Was Built In This Phase

| File | Purpose |
|---|---|
| `app.py` | Flask application entry point |
| `config.py` | Configuration management (reads from .env) |
| `db.py` | Database connection helper |
| `requirements.txt` | Python dependencies (only 3) |
| `.env` / `.env.example` | Environment variables (secrets) |
| `.gitignore` | Keeps secrets and junk out of Git |
| `routes/__init__.py` | Empty package — routes added in later phases |
| `helpers/__init__.py` | Empty package — helpers added in later phases |
| `templates/base.html` | Master layout (navbar, footer, Bootstrap CDN) |
| `templates/home.html` | Landing page |
| `static/css/style.css` | 3 custom CSS rules (rest is Bootstrap) |

---

## File-by-File Interview Defense

---

### `app.py` — The Entry Point

```python
from flask import Flask, render_template
from config import Config

app = Flask(__name__)
app.config.from_object(Config)

@app.route('/')
def home():
    return render_template('home.html')

if __name__ == '__main__':
    app.run(debug=True)
```

**Q: What does `Flask(__name__)` do?**
> It creates the Flask application object. `__name__` tells Flask where to find
> templates and static files — it uses the module's location as the root directory.

**Q: What does `app.config.from_object(Config)` do?**
> It loads all class attributes from our `Config` class as app configuration.
> Flask stores them in `app.config`, which is a dictionary-like object.
> For example, `Config.SECRET_KEY` becomes accessible as `app.config['SECRET_KEY']`.

**Q: What is `@app.route('/')`?**
> It's a decorator that maps a URL path to a Python function. When a user visits
> `http://localhost:5000/`, Flask calls the `home()` function and returns the result
> to the browser.

**Q: What does `render_template('home.html')` do?**
> It loads `templates/home.html`, processes any Jinja2 tags (`{{ }}`, `{% %}`),
> and returns the final HTML string. Flask looks in the `templates/` folder by default.

**Q: Why `debug=True`?**
> Two reasons:
> 1. Auto-reload: Flask restarts when you save a file (no manual restart needed)
> 2. Error pages: Shows detailed tracebacks in the browser instead of generic "500 Error"
> You should NEVER use `debug=True` in production — it exposes internal code.

**Q: What is `if __name__ == '__main__'`?**
> It ensures `app.run()` only executes when you run the file directly (`python app.py`),
> not when it's imported by another module. This is a standard Python pattern.

---

### `config.py` — Configuration Management

```python
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-fallback-key-change-in-production')
    MYSQL_HOST = os.getenv('MYSQL_HOST', 'localhost')
    MYSQL_PORT = int(os.getenv('MYSQL_PORT', 3306))
    MYSQL_USER = os.getenv('MYSQL_USER', 'root')
    MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', '')
    MYSQL_DATABASE = os.getenv('MYSQL_DATABASE', 'securepay_db')
```

**Q: Why use environment variables instead of hardcoding values?**
> Three reasons:
> 1. **Security**: Passwords and secret keys stay out of source code and Git history
> 2. **Portability**: Same code works on dev laptop and production server — just change .env
> 3. **12-Factor App**: This follows the industry-standard "12-Factor App" methodology
>    which says config should come from the environment

**Q: What does `load_dotenv()` do?**
> It reads the `.env` file and loads each `KEY=VALUE` pair into the system's environment
> variables. After this call, `os.getenv('SECRET_KEY')` returns the value from `.env`.

**Q: What is `os.getenv('SECRET_KEY', 'dev-fallback')`?**
> `os.getenv(key, default)` reads an environment variable. If it doesn't exist,
> it returns the default value. The fallback ensures the app doesn't crash if `.env`
> is missing, but the fallback key is insecure — it's only for development convenience.

**Q: What is SECRET_KEY used for?**
> Flask uses it to **cryptographically sign session cookies**. Without it, an attacker
> could forge session data and impersonate any user. It must be a long random string
> and must be kept secret.

---

### `db.py` — Database Connection Helper

```python
import mysql.connector
from config import Config

def get_db_connection():
    connection = mysql.connector.connect(
        host=Config.MYSQL_HOST,
        port=Config.MYSQL_PORT,
        user=Config.MYSQL_USER,
        password=Config.MYSQL_PASSWORD,
        database=Config.MYSQL_DATABASE
    )
    return connection
```

**Q: Why not use an ORM like SQLAlchemy?**
> This project deliberately uses raw SQL with parameterized queries because:
> 1. It demonstrates SQL skills directly (which is the point for interviews)
> 2. You have full control over the exact queries being executed
> 3. It's simpler to understand — no ORM "magic" to debug
> 4. ORMs can generate inefficient SQL; raw queries let you optimize

**Q: Why `mysql-connector-python` specifically?**
> It's the official MySQL driver maintained by Oracle. Alternatives like `PyMySQL`
> or `mysqlclient` work too, but `mysql-connector-python` is pure Python (no C
> compilation needed) and has straightforward API.

**Q: Why `dictionary=True` when creating cursors? (used in routes)**
> Without it: `cursor.fetchone()` returns `(1, 'john', 'john@email.com')` — a tuple
> With it: returns `{'id': 1, 'username': 'john', 'email': 'john@email.com'}` — a dict
> Dicts are easier to use in templates: `{{ user.username }}` vs `{{ user[1] }}`

**Q: Why create a new connection for each request instead of reusing one?**
> Database connections are NOT thread-safe. If two web requests share one connection,
> they can interfere with each other's transactions. Creating a new connection per
> request is the simplest safe approach. For high-traffic apps, you'd use connection
> pooling, but that's overkill for this project.

---

### `requirements.txt` — Dependencies

```
flask                    # Web framework
mysql-connector-python   # Official MySQL driver
python-dotenv            # Loads .env file into environment variables
```

**Q: Why only 3 dependencies?**
> Minimal dependencies = less to maintain, fewer security vulnerabilities, easier
> to understand. Each one serves a clear purpose:
> - Flask: the web framework
> - mysql-connector-python: talk to MySQL
> - python-dotenv: load .env files
> Flask itself pulls in sub-dependencies (Werkzeug, Jinja2, etc.) but we don't
> need to list those — pip installs them automatically.

---

### `.env` / `.env.example` — Secrets Management

**Q: Why two files? Why not just `.env`?**
> - `.env` has REAL secrets (your actual password) — it's **gitignored**, never committed
> - `.env.example` is a TEMPLATE showing what variables are needed — it IS committed
> - A new developer clones the repo, copies `.env.example` to `.env`, fills in their
>   own values, and the app works. They never see YOUR secrets.

**Q: What happens if `.env` is accidentally committed to Git?**
> The secrets are now in the Git history permanently (even if you delete the file later).
> You'd need to rotate all secrets (change passwords, generate new keys) and use
> `git filter-branch` or BFG Repo Cleaner to purge the history.

---

### `.gitignore`

**Q: Why is `__pycache__/` ignored?**
> Python creates `__pycache__/` with compiled `.pyc` bytecode files to speed up imports.
> These are machine-specific, regenerated automatically, and shouldn't be in version control.

---

### `templates/base.html` — Master Layout (Jinja2 Template Inheritance)

**Q: How does Jinja2 template inheritance work?**
> Think of it like Python class inheritance:
> - `base.html` is the **parent**: defines the page skeleton with empty slots (`{% block content %}`)
> - `home.html` is the **child**: starts with `{% extends "base.html" %}` and fills the slots
> - Result: Flask combines them into one complete HTML page
>
> This means every page automatically gets the same navbar, footer, and Bootstrap CDN
> without any copy-pasting. Change `base.html` once = change ALL pages.

**Q: What is `{{ url_for('home') }}`?**
> `url_for()` generates URLs from function names instead of hardcoding paths.
> `url_for('home')` → `/` (because the `home()` function is mapped to `/`)
> Why? If you rename a route from `/` to `/index`, all your links update automatically.

**Q: What is `{{ url_for('static', filename='css/style.css') }}`?**
> Flask has a built-in route for serving static files from the `static/` folder.
> This generates the correct URL path to the CSS file.

**Q: What does `get_flashed_messages(with_categories=true)` do?**
> Flask's `flash()` function stores one-time messages in the session.
> `get_flashed_messages()` retrieves and DELETES them (they only show once).
> `with_categories=true` gives us the category ('success', 'danger', 'warning')
> so we can style the alert accordingly with Bootstrap CSS classes.

**Q: Why did you hit a bug with HTML comments containing Jinja tags?**
> Jinja2 processes `{% %}` tags EVEN inside HTML comments (`<!-- -->`).
> So `<!-- {% block content %} -->` was treated as a real block definition, causing
> "block defined twice" errors.
> Fix: Use `{# ... #}` (Jinja's own comment syntax) which truly hides content
> from the template engine. This shows understanding of template engine internals.

---

### `static/css/style.css` — Custom Styles

```css
.hero-section {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
}
.card {
    transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.card:hover {
    transform: translateY(-4px);
    box-shadow: 0 8px 25px rgba(0, 0, 0, 0.15) !important;
}
```

**Q: Why only 3 CSS rules? Why not write all styles from scratch?**
> Bootstrap 5 CDN handles 95% of styling — layout, typography, buttons, cards, navbar.
> Writing custom CSS for things Bootstrap already provides is wasted effort.
> We only write custom CSS for things Bootstrap DOESN'T provide (gradient backgrounds,
> hover animations). This shows pragmatic decision-making.

---

## Architecture Decisions to Defend

**Q: Why Flask and not Django?**
> Django is a "batteries-included" framework with ORM, admin panel, auth, etc.
> For this project:
> - We want raw SQL (not ORM) to showcase database skills
> - We want to build auth ourselves to showcase security knowledge
> - Flask is lightweight — less "magic", easier to understand every line
> - The project scope is small, so Django's extras aren't needed

**Q: Why server-side rendering (Jinja2) and not React/Vue?**
> 1. This is a backend-focused project — the frontend just needs to work
> 2. Jinja2 templates are simple HTML with some Python logic — no build step
> 3. No JavaScript framework means fewer dependencies and less complexity
> 4. For a 1-2 day project, server-side rendering is the pragmatic choice

**Q: Why MySQL and not PostgreSQL or SQLite?**
> - MySQL is widely used in production and interviews
> - MySQL 8.x supports CHECK constraints (earlier versions silently ignored them)
> - SQLite doesn't support concurrent writes or some constraint types
> - PostgreSQL would also work well, but MySQL is more commonly asked about
