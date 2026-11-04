"""Startup configuration checks.

The app refuses to start with a clear list of problems instead of failing later with a KeyError
or, worse, running with unsafe settings (for example live Razorpay keys on a dev machine).
"""
import ipaddress
import os
from functools import lru_cache
from urllib.parse import urlparse

APP_ENVS = ("development", "test", "production")
MIN_QR_EXPIRY_MINUTES = 3  # Razorpay requires close_by to be a few minutes in the future
MAX_QR_EXPIRY_MINUTES = 1440


class ConfigError(RuntimeError):
    pass


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def app_env() -> str:
    return _env("APP_ENV", "development").lower()


def is_production() -> bool:
    return app_env() == "production"


def _bool_setting(name: str, default: str, errors: list[str]) -> None:
    if _env(name, default).lower() not in ("true", "false"):
        errors.append(f"{name} must be 'true' or 'false'")


def collect_errors() -> list[str]:
    errors: list[str] = []
    env = app_env()
    prod = env == "production"
    if env not in APP_ENVS:
        errors.append(f"APP_ENV must be one of {', '.join(APP_ENVS)} (got '{env}')")

    db_scheme = _env("DATABASE_URL").split("://", 1)[0] if "://" in _env("DATABASE_URL") else ""
    if db_scheme != "postgresql" and not db_scheme.startswith("postgresql+"):
        errors.append("DATABASE_URL must be a postgresql:// (or postgresql+driver://) URL")

    jwt_secret = _env("JWT_SECRET")
    if not jwt_secret:
        errors.append("JWT_SECRET is required")
    elif prod and len(jwt_secret) < 32:
        errors.append("JWT_SECRET must be at least 32 characters in production")

    _bool_setting("COOKIE_SECURE", "", errors)
    if prod and _env("COOKIE_SECURE").lower() != "true":
        errors.append("COOKIE_SECURE must be 'true' in production")

    origins = [o.strip() for o in _env("FRONTEND_URL").split(",") if o.strip()]
    if not origins:
        errors.append("FRONTEND_URL is required")
    for origin in origins:
        parsed = urlparse(origin)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            errors.append(f"FRONTEND_URL entry '{origin}' is not a valid http(s) URL")
        elif prod and parsed.scheme != "https":
            errors.append(f"FRONTEND_URL entry '{origin}' must use https in production")

    expiry = _env("QR_EXPIRY_MINUTES")
    if not expiry.isdigit() or not MIN_QR_EXPIRY_MINUTES <= int(expiry) <= MAX_QR_EXPIRY_MINUTES:
        errors.append(f"QR_EXPIRY_MINUTES must be a whole number from {MIN_QR_EXPIRY_MINUTES} to {MAX_QR_EXPIRY_MINUTES}")

    errors.extend(_razorpay_errors(prod))

    for entry in _split(_env("TRUSTED_PROXIES")):
        try:
            ipaddress.ip_network(entry, strict=False)
        except ValueError:
            errors.append(f"TRUSTED_PROXIES entry '{entry}' is not an IP address or CIDR range")

    if _env("LOG_FORMAT", "text").lower() not in ("text", "json"):
        errors.append("LOG_FORMAT must be 'text' or 'json'")
    _bool_setting("RUN_MIGRATIONS_ON_STARTUP", _migrate_default(), errors)
    if prod and run_migrations_on_startup():
        errors.append("RUN_MIGRATIONS_ON_STARTUP must be false in production; run `python migrate.py` as a deployment step")
    if prod and _env("LOCAL_POSTGRES_BOOTSTRAP").lower() == "true":
        errors.append("LOCAL_POSTGRES_BOOTSTRAP must not be enabled in production")
    return errors


def _razorpay_errors(prod: bool) -> list[str]:
    """Keep Razorpay test and live environments apart.

    - Live keys (rzp_live_) are only accepted when APP_ENV=production.
    - In production, RAZORPAY_EXPECTED_MODE must be set, so a test deployment can never be
      silently switched to live keys (or the reverse) by editing only the key.
    """
    errors = []
    key_id = _env("RAZORPAY_KEY_ID")
    secret = _env("RAZORPAY_KEY_SECRET")
    expected = _env("RAZORPAY_EXPECTED_MODE").lower()
    mode = "test" if key_id.startswith("rzp_test_") else "live" if key_id.startswith("rzp_live_") else None

    if key_id and mode is None:
        errors.append("RAZORPAY_KEY_ID must start with rzp_test_ or rzp_live_")
    if bool(key_id) != bool(secret):
        errors.append("RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must be set together")
    if expected and expected not in ("test", "live"):
        errors.append("RAZORPAY_EXPECTED_MODE must be 'test' or 'live'")
    if prod and not expected:
        errors.append("RAZORPAY_EXPECTED_MODE ('test' or 'live') is required in production")
    if mode and expected in ("test", "live") and mode != expected:
        errors.append(f"RAZORPAY_KEY_ID is a {mode} key but RAZORPAY_EXPECTED_MODE is '{expected}'")
    if mode == "live" and not prod:
        errors.append("Live Razorpay keys (rzp_live_) are only allowed when APP_ENV=production")
    if expected == "live" and not prod:
        errors.append("RAZORPAY_EXPECTED_MODE=live is only allowed when APP_ENV=production")
    return errors


def validate() -> None:
    errors = collect_errors()
    if errors:
        raise ConfigError("Invalid configuration:\n  - " + "\n  - ".join(errors))


def _split(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


@lru_cache(maxsize=1)
def trusted_proxies() -> tuple:
    return tuple(ipaddress.ip_network(v, strict=False) for v in _split(_env("TRUSTED_PROXIES")))


def is_trusted_proxy(host: str | None) -> bool:
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(ip in net for net in trusted_proxies())


def _migrate_default() -> str:
    # Convenient locally; in production migrations are an explicit release step, never done by app workers.
    return "false" if is_production() else "true"


def run_migrations_on_startup() -> bool:
    return _env("RUN_MIGRATIONS_ON_STARTUP", _migrate_default()).lower() == "true"
