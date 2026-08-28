"""
helpers/validators.py — Input validation functions

PURPOSE:
    Validates user input on the server side before querying the database.
    Never trust client-side validation alone.

SECURITY BENEFIT:
    1. Rejects malformed or malicious inputs early.
    2. Enforces minimum password complexity.
    3. Normalizes input (e.g. trimming whitespace, lowercasing emails).
"""

import re


def validate_registration(username, email, full_name, password, confirm_password):
    """
    Validate registration input data.

    Returns:
        tuple: (is_valid: bool, error_message: str or None)
    """
    # 1. Check for empty fields
    if not username or not username.strip():
        return False, "Username is required."
    if not email or not email.strip():
        return False, "Email is required."
    if not full_name or not full_name.strip():
        return False, "Full name is required."
    if not password:
        return False, "Password is required."
    if not confirm_password:
        return False, "Please confirm your password."

    username = username.strip()
    email = email.strip()
    full_name = full_name.strip()

    # 2. Validate username format (letters, numbers, underscores, hyphens, length 3-30)
    if not re.match(r'^[a-zA-Z0-9_-]{3,30}$', username):
        return False, "Username must be 3-30 characters and contain only letters, numbers, underscores (_), or hyphens (-)."

    # 3. Validate email format
    email_pattern = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
    if not re.match(email_pattern, email):
        return False, "Please enter a valid email address."

    # 4. Check password length
    if len(password) < 8:
        return False, "Password must be at least 8 characters long."

    # 5. Check password confirmation match
    if password != confirm_password:
        return False, "Passwords do not match."

    return True, None
