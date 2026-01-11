"""
WSGI entry point for production servers (e.g., gunicorn).
"""

from .app import create_app

app = create_app()
