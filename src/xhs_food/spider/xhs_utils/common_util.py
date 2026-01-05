import os
from loguru import logger

def load_env():
    """Load XHS cookies from environment or meet settings."""
    # Try to load from environment variable first
    cookies_str = os.getenv('XHS_COOKIES')
    if cookies_str:
        return cookies_str
    
    # Fallback: try to load from Spider_XHS .env
    try:
        from dotenv import load_dotenv
        env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../../../../Spider_XHS/.env'))
        if os.path.exists(env_path):
            load_dotenv(env_path)
            cookies_str = os.getenv('COOKIES')
            if cookies_str:
                return cookies_str
    except Exception as e:
        logger.warning(f"Failed to load from Spider_XHS .env: {e}")
    
    logger.warning("No XHS cookies found. Set XHS_COOKIES environment variable.")
    return None

def init():
    """Initialize data directories."""
    from pathlib import Path
    base_dir = Path(__file__).parent.parent
    data_dir = base_dir / 'datas'
    media_base_path = data_dir / 'media_datas'
    excel_base_path = data_dir / 'excel_datas'
    
    for base_path in [media_base_path, excel_base_path]:
        if not base_path.exists():
            base_path.mkdir(parents=True)
            logger.info(f'Created directory {base_path}')
    
    cookies_str = load_env()
    base_path = {
        'media': str(media_base_path),
        'excel': str(excel_base_path),
    }
    return cookies_str, base_path
