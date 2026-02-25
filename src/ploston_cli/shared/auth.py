"""Authentication utilities for ploston-cli.

For OSS: simple token pass-through. No validation, no principal resolution.
Tokens are opaque strings passed to CP.

Pro auth (PRO_AUTH_FOUNDATION_SPEC) extends this module with principal-aware
validation. OSS code doesn't change — Pro adds middleware on CP side.
"""

import os
from pathlib import Path

from .paths import TOKENS_DIR


def get_token(
    source: str,
    token_arg: str | None = None,
    env_var: str | None = None,
) -> str | None:
    """Resolve token from: CLI arg > env var > stored file.

    Priority order:
    1. Explicit CLI argument (--token)
    2. Environment variable (e.g., PLOSTON_TOKEN)
    3. Stored token file (~/.ploston/tokens/{source}.token)

    Args:
        source: Token source name (e.g., "bridge", "runner", "cli")
        token_arg: Token passed via CLI argument
        env_var: Environment variable name to check

    Returns:
        Token string if found, None if no auth available

    Usage:
        Bridge: get_token("bridge", token_arg, "PLOSTON_TOKEN")
        Runner: get_token("runner", token_arg, "PLOSTON_RUNNER_TOKEN")
        CLI: get_token("cli", token_arg, "PLOSTON_TOKEN")
    """
    # Priority 1: CLI argument
    if token_arg:
        return token_arg

    # Priority 2: Environment variable
    if env_var and os.environ.get(env_var):
        return os.environ[env_var]

    # Priority 3: Stored token file
    token_file = TOKENS_DIR / f"{source}.token"
    if token_file.exists():
        return token_file.read_text().strip()

    return None


def auth_headers(token: str | None) -> dict[str, str]:
    """Build Authorization header dict.

    Args:
        token: Bearer token string

    Returns:
        Dict with Authorization header, or empty dict if no token
    """
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def save_token(source: str, token: str) -> None:
    """Save a token to the token file.

    Args:
        source: Token source name (e.g., "bridge", "runner", "cli")
        token: Token string to save
    """
    token_file = TOKENS_DIR / f"{source}.token"
    token_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    token_file.write_text(token)
    # Set file permissions to owner-only (600)
    token_file.chmod(0o600)


def delete_token(source: str) -> bool:
    """Delete a stored token file.

    Args:
        source: Token source name (e.g., "bridge", "runner", "cli")

    Returns:
        True if file was deleted, False if it didn't exist
    """
    token_file = TOKENS_DIR / f"{source}.token"
    if token_file.exists():
        token_file.unlink()
        return True
    return False


def get_token_file_path(source: str) -> Path:
    """Get the path to a token file.

    Args:
        source: Token source name (e.g., "bridge", "runner", "cli")

    Returns:
        Path to the token file
    """
    return TOKENS_DIR / f"{source}.token"
