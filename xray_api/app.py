"""
X-Ray API - Flask Application Entry Point
"""

import os
from flask import Flask, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from .models import db
from .routes.ingest import ingest_bp
from .routes.query import query_bp
from .routes.stream import stream_bp


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
    app.config['XRAY_API_KEY'] = os.getenv('XRAY_API_KEY')
    app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB max request size
    
    # Initialize extensions
    CORS(app)
    db.init_app(app)
    
    # API Key authentication middleware
    @app.before_request
    def check_api_key():
        from flask import request, jsonify
        
        # Skip auth for health endpoint
        if request.path == '/health':
            return None
        
        # Skip if no API key is configured (local dev mode)
        if not app.config['XRAY_API_KEY']:
            return None
        
        # Check API key header
        provided_key = request.headers.get('X-API-Key')
        if not provided_key or provided_key != app.config['XRAY_API_KEY']:
            return jsonify({"error": "Invalid or missing API key"}), 401
        
        return None
    
    # Register blueprints
    app.register_blueprint(ingest_bp)
    app.register_blueprint(query_bp)
    app.register_blueprint(stream_bp)
    
    # Global error handlers for consistent JSON error responses
    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({"error": "Bad request", "detail": str(e)}), 400
    
    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Not found"}), 404
    
    @app.errorhandler(413)
    def payload_too_large(e):
        return jsonify({"error": "Payload too large", "max_bytes": app.config['MAX_CONTENT_LENGTH']}), 413
    
    @app.errorhandler(500)
    def internal_error(e):
        return jsonify({"error": "Internal server error"}), 500
    
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
