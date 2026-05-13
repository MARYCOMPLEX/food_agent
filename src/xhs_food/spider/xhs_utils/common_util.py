import os
from loguru import logger


_PLACEHOLDER_PATTERNS = (
    "your_", "xxx", "<your", "<replace", "todo",
    "example", "placeholder",
)


def _looks_like_real_cookie(s: str) -> bool:
    """过滤 .env 里的占位字符串，比如 'your_xhs_cookies_here'."""
    s_low = s.strip().lower()
    if not s_low:
        return False
    if any(p in s_low for p in _PLACEHOLDER_PATTERNS):
        return False
    # 真 cookie 至少包含 = 和 ;，或者至少一个 = 加常见字段名
    if "=" not in s:
        return False
    return True


def load_env():
    """Load XHS cookies, in order of precedence:

    1. xhs_food.auth profile (recommended; refreshed by `python -m xhs_food.auth qr`)
    2. XHS_COOKIES env var (legacy / manual override)
    3. Spider_XHS .env (legacy fallback)

    Profile wins over the env var because the env var is frequently stale
    (cookies expire weekly) while the profile is updated by every login.
    """
    try:
        from xhs_food.auth import get_cookies
        profile_name = os.getenv('XHS_PROFILE', 'default')
        cookies_str = get_cookies(profile_name)
        if cookies_str and 'web_session=' in cookies_str:
            logger.debug(f"XHS cookies loaded from auth profile '{profile_name}'")
            return cookies_str
    except Exception as e:
        logger.debug(f"auth profile lookup failed: {e}")

    cookies_str = os.getenv('XHS_COOKIES')
    if cookies_str and _looks_like_real_cookie(cookies_str):
        logger.warning(
            "Falling back to XHS_COOKIES env var — profile not found or has no "
            "web_session. Run `uv run python -m xhs_food.auth qr` to refresh."
        )
        return cookies_str

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

    logger.warning(
        "No XHS cookies found. Either set XHS_COOKIES env var or run "
        "`python -m xhs_food.auth qr` to log in."
    )
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
