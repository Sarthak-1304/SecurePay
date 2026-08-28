"""
helpers/decorators.py — Authentication & Authorization Decorators

PURPOSE:
    Protects Flask routes by checking if the user is authenticated (logged in)
    or authorized (has the required role like 'admin').

HOW IT WORKS:
    Decorators wrap view functions and inspect the Flask `session` dictionary
    before allowing the request to proceed.
"""

from functools import wraps
from flask import session, flash, redirect, url_for, request


def login_required(view_function):
    """
    Decorator to ensure a user is logged in before accessing a route.
    If not logged in, redirects to the login page with a flash message.
    """
    @wraps(view_function)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for('auth.login', next=request.path))
        return view_function(*args, **kwargs)
    return decorated_function


def admin_required(view_function):
    """
    Decorator to ensure the logged-in user has the 'admin' role.
    If not an admin, redirects to the home page with an unauthorized message.
    """
    @wraps(view_function)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for('auth.login', next=request.path))

        if session.get('role') != 'admin':
            flash("Access denied: Administrator privileges required.", "danger")
            return redirect(url_for('home'))

        return view_function(*args, **kwargs)
    return decorated_function
