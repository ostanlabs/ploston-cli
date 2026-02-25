"""Token storage and authentication for runner.

Handles:
- Storing and retrieving authentication tokens
- Token file management
- Secure token handling
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def get_default_token_path() -> Path:
    """Get the default path for storing runner tokens.

    Returns:
        Path to the token file in user's config directory
    """
    # Use XDG_CONFIG_HOME if set, otherwise ~/.config
    config_home = os.environ.get("XDG_CONFIG_HOME")
    if config_home:
        base = Path(config_home)
    else:
        base = Path.home() / ".config"

    return base / "ploston" / "runner_token.json"


class TokenStorage:
    """Manages runner authentication tokens.

    Stores tokens securely in the user's config directory.
    """

    def __init__(self, token_path: Path | None = None):
        """Initialize token storage.

        Args:
            token_path: Optional custom path for token file
        """
        self._token_path = token_path or get_default_token_path()
        self._token_data: dict[str, Any] = {}

    @property
    def token_path(self) -> Path:
        """Get the token file path."""
        return self._token_path

    def load(self) -> bool:
        """Load token from file.

        Returns:
            True if token was loaded successfully
        """
        if not self._token_path.exists():
            logger.debug(f"Token file not found: {self._token_path}")
            return False

        try:
            with open(self._token_path) as f:
                self._token_data = json.load(f)
            logger.debug(f"Loaded token from {self._token_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to load token: {e}")
            return False

    def save(self) -> bool:
        """Save token to file.

        Returns:
            True if token was saved successfully
        """
        try:
            # Ensure directory exists
            self._token_path.parent.mkdir(parents=True, exist_ok=True)

            # Write with restricted permissions
            with open(self._token_path, "w") as f:
                json.dump(self._token_data, f, indent=2)

            # Set file permissions to owner-only (600)
            os.chmod(self._token_path, 0o600)

            logger.debug(f"Saved token to {self._token_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save token: {e}")
            return False

    def get_token(self, cp_url: str) -> str | None:
        """Get token for a Control Plane URL.

        Args:
            cp_url: Control Plane URL

        Returns:
            Token string if found, None otherwise
        """
        return self._token_data.get(cp_url, {}).get("token")

    def get_runner_id(self, cp_url: str) -> str | None:
        """Get runner ID for a Control Plane URL.

        Args:
            cp_url: Control Plane URL

        Returns:
            Runner ID if found, None otherwise
        """
        return self._token_data.get(cp_url, {}).get("runner_id")

    def set_token(self, cp_url: str, token: str, runner_id: str | None = None) -> None:
        """Set token for a Control Plane URL.

        Args:
            cp_url: Control Plane URL
            token: Authentication token
            runner_id: Optional runner ID
        """
        self._token_data[cp_url] = {
            "token": token,
            "runner_id": runner_id,
        }

    def clear_token(self, cp_url: str) -> None:
        """Clear token for a Control Plane URL.

        Args:
            cp_url: Control Plane URL
        """
        if cp_url in self._token_data:
            del self._token_data[cp_url]

    def clear_all(self) -> None:
        """Clear all stored tokens."""
        self._token_data = {}

    def delete_file(self) -> bool:
        """Delete the token file.

        Returns:
            True if file was deleted or didn't exist
        """
        try:
            if self._token_path.exists():
                self._token_path.unlink()
                logger.debug(f"Deleted token file: {self._token_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete token file: {e}")
            return False
