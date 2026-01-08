"""
X-Ray API - Flask Application Entry Point
"""

import os
from flask import Flask
from flask_cors import CORS
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from .models import db
from .routes.ingest import ingest_bp


def create_app():
    """Create and configure the Flask application"""
    app = Flask(__name__)
    
    # Configuration
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
        'DATABASE_URL',
        'sqlite:///xray.db'  # Fallback to SQLite for local dev
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['JSON_SORT_KEYS'] = False
    
    # Initialize extensions
    CORS(app)
    db.init_app(app)
    
    # Register blueprints
    app.register_blueprint(ingest_bp)
    
    # Health check endpoint
    @app.route('/health')
    def health():
        return {"status": "healthy"}
    
    # Create tables
    with app.app_context():
        db.create_all()
    
    return app


# For running directly: python -m xray_api.app
if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5000)
