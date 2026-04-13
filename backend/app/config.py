import os


class Config:
    DEBUG = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'
    HOST = os.getenv('FLASK_HOST', '0.0.0.0')
    PORT = int(os.getenv('FLASK_PORT', '5001'))
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB
    ALLOWED_EXTENSIONS = {'pdf', 'md', 'txt', 'markdown'}
    DEFAULT_CHUNK_SIZE = 500
    DEFAULT_CHUNK_OVERLAP = 50
    DEFAULT_MAX_ROUNDS = int(os.getenv('DEFAULT_MAX_ROUNDS', '10'))
    UPLOAD_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        '..', 'uploads'
    )
    CLAUDE_MODEL = os.getenv('CLAUDE_MODEL', 'sonnet')  # sonnet, opus, haiku
