"""MiroFish Backend - Flask app factory (claude -p powered)."""

import os
import logging

from flask import Flask
from flask_cors import CORS

from .config import Config

logger = logging.getLogger('mirofish')


def create_app(config_class=Config):
    """Create and configure Flask application."""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Ensure upload directory exists
    os.makedirs(app.config.get('UPLOAD_DIR', 'uploads'), exist_ok=True)

    # JSON: display non-ASCII directly
    if hasattr(app, 'json') and hasattr(app.json, 'ensure_ascii'):
        app.json.ensure_ascii = False

    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if app.config['DEBUG'] else logging.INFO,
        format='%(asctime)s [%(name)s] %(levelname)s: %(message)s'
    )

    # CORS
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # Initialize database
    from .models.database import init_db
    init_db()

    # Register simulation cleanup on shutdown
    from .services.simulation_runner import SimulationRunner
    SimulationRunner.register_cleanup()

    # Register blueprints
    from .api import graph_bp, simulation_bp, report_bp
    app.register_blueprint(graph_bp, url_prefix='/api/graph')
    app.register_blueprint(simulation_bp, url_prefix='/api/simulation')
    app.register_blueprint(report_bp, url_prefix='/api/report')

    # Health check
    @app.route('/health')
    def health():
        return {'status': 'ok', 'service': 'MiroFish Backend (claude-powered)'}

    logger.info("MiroFish Backend initialized")
    return app
