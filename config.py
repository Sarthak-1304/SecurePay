"""
config.py — Application configuration

HOW IT WORKS:
1. python-dotenv loads variables from the .env file into the environment.
2. os.getenv() reads those variables.
3. The Config class bundles them into one object Flask can use.

WHY THIS PATTERN:
- Secrets (passwords, keys) stay in .env, which is gitignored.
- The same code works on your laptop and on a server — just change .env.
- Flask reads config with: app.config.from_object(Config)
"""

import os
from dotenv import load_dotenv

# Load .env file into environment variables
# This must be called BEFORE reading os.getenv()
load_dotenv()


class Config:
    """All application settings in one place."""

    # Flask uses this to sign session cookies (keeps sessions tamper-proof)
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-fallback-key-change-in-production')

    # MySQL connection settings
    MYSQL_HOST = os.getenv('MYSQL_HOST', 'localhost')
    MYSQL_PORT = int(os.getenv('MYSQL_PORT', 3306))
    MYSQL_USER = os.getenv('MYSQL_USER', 'root')
    MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', '')
    MYSQL_DATABASE = os.getenv('MYSQL_DATABASE', 'securepay_db')
