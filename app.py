"""
app.py — Flask application entry point

HOW FLASK STARTS:
1. Python runs this file: python app.py
2. Flask(__name__) creates the app object
3. app.config.from_object(Config) loads database settings, secret key, etc.
4. @app.route() decorators map URLs to Python functions
5. app.run(debug=True) starts a local development server on http://127.0.0.1:5000

HOW TEMPLATES WORK:
- render_template('home.html') looks in the templates/ folder
- Jinja2 processes the HTML, replacing {{ variables }} and {% logic %}
- home.html extends base.html (like class inheritance)
- base.html has the navbar, Bootstrap CDN, and a {% block content %} placeholder
- home.html fills in that content block

HOW BLUEPRINTS WORK (coming in Phase 2):
- Instead of putting ALL routes in app.py, we split them into files:
    routes/auth.py    → /login, /register, /logout
    routes/wallet.py  → /dashboard, /deposit, /withdraw, /transfer
    routes/admin.py   → /admin/...
- Each file is a Flask "Blueprint" — a mini-app that gets registered with the main app
- This keeps the code organized as the project grows
"""

from flask import Flask, render_template
from config import Config


# =============================================
# Create the Flask application
# =============================================
app = Flask(__name__)

# Load settings from our Config class (secret key, database, etc.)
app.config.from_object(Config)

# Register Blueprints
from routes.auth import auth_bp
from routes.wallet import wallet_bp
from routes.admin import admin_bp
app.register_blueprint(auth_bp)
app.register_blueprint(wallet_bp)
app.register_blueprint(admin_bp)



# =============================================
# Routes
# =============================================
# Each @app.route() maps a URL to a Python function.
# When someone visits that URL, Flask calls the function
# and sends the return value back to the browser.
# =============================================

from flask import session, redirect, url_for

@app.route('/')
def home():
    """Home page — if logged in, redirect to dashboard; otherwise show landing page."""
    if 'user_id' in session:
        return redirect(url_for('wallet.dashboard'))
    return render_template('home.html')


# =============================================
# Start the development server
# =============================================
if __name__ == '__main__':
    # debug=True means:
    #   1. Auto-reload when you save a file (no need to restart manually)
    #   2. Show detailed error pages in the browser
    #   3. NEVER use debug=True in production!
    print("=" * 50)
    print("  SecurePay is running!")
    print("  Open: http://127.0.0.1:5000")
    print("=" * 50)
    app.run(debug=True)
