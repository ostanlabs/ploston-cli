"""Asset manager for bundled deployment configuration files.

This module provides the AssetManager class which copies static configuration
files (Prometheus, Grafana, Loki, Tempo, OTEL, etc.) from the bundled assets
directory to the target deployment directory (~/.ploston/).

Assets are bundled inside the ploston-cli package and accessed via
importlib.resources, ensuring they work correctly whether installed from
a wheel, editable install, or source checkout.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

# Default paths
PLOSTON_DIR = Path.home() / ".ploston"

# Asset package references
_DOCKER_OBS_PACKAGE = "ploston_cli.bootstrap.assets.docker.observability"
_K8S_OBS_PACKAGE = "ploston_cli.bootstrap.assets.k8s.observability"


class AssetManager:
    """Manage bundled deployment assets.

    Copies static configuration files from the package's assets directory
    to the target deployment directory. This replaces the old approach of
    generating configs programmatically via Python dicts.
    """

    def __init__(self, target_dir: Path | None = None):
        """Initialize asset manager.

        Args:
            target_dir: Target directory for deployment files.
                       Defaults to ~/.ploston/
        """
        self.target_dir = target_dir or PLOSTON_DIR

    def deploy_observability_docker(self, overwrite: bool = False) -> Path:
        """Deploy Docker observability assets to target directory.

        Copies the observability compose overlay and all supporting config
        files (prometheus, grafana, loki, tempo, otel) to the target dir.

        The compose overlay file is placed at:
            {target_dir}/observability/docker-compose.observability.yaml

        Config files are placed alongside it so that relative volume mounts
        in the compose file resolve correctly:
            {target_dir}/observability/prometheus/prometheus.yml
            {target_dir}/observability/loki/loki-config.yaml
            etc.

        Args:
            overwrite: If True, overwrite existing files.

        Returns:
            Path to the observability compose overlay file.
        """
        obs_dir = self.target_dir / "observability"
        obs_dir.mkdir(parents=True, exist_ok=True)

        # Copy the entire observability asset tree
        self._copy_asset_tree(_DOCKER_OBS_PACKAGE, obs_dir, overwrite=overwrite)

        return obs_dir / "docker-compose.observability.yaml"

    def deploy_observability_k8s(self, overwrite: bool = False) -> Path:
        """Deploy K8s observability manifests to target directory.

        Copies all K8s observability manifests to:
            {target_dir}/k8s/observability/

        Args:
            overwrite: If True, overwrite existing files.

        Returns:
            Path to the K8s observability manifest directory.
        """
        k8s_obs_dir = self.target_dir / "k8s" / "observability"
        k8s_obs_dir.mkdir(parents=True, exist_ok=True)

        self._copy_asset_tree(_K8S_OBS_PACKAGE, k8s_obs_dir, overwrite=overwrite)

        return k8s_obs_dir

    def _copy_asset_tree(
        self,
        package: str,
        target: Path,
        overwrite: bool = False,
    ) -> None:
        """Recursively copy all files from a package's directory to target.

        Args:
            package: Dotted package name containing the assets.
            target: Target directory to copy files into.
            overwrite: If True, overwrite existing files.
        """
        target.mkdir(parents=True, exist_ok=True)

        # Use importlib.resources to traverse the asset package
        asset_files = resources.files(package)

        self._copy_traversable(asset_files, target, overwrite)

    def _copy_traversable(
        self,
        traversable: resources.abc.Traversable,
        target: Path,
        overwrite: bool,
    ) -> None:
        """Recursively copy a Traversable tree to a target directory.

        Args:
            traversable: The importlib.resources Traversable to copy from.
            target: Target directory.
            overwrite: If True, overwrite existing files.
        """
        for item in traversable.iterdir():
            dest = target / item.name

            if item.is_file():
                # Skip __init__.py and __pycache__
                if item.name == "__init__.py" or item.name.endswith(".pyc"):
                    continue

                if dest.exists() and not overwrite:
                    continue

                # Read and write the file
                dest.parent.mkdir(parents=True, exist_ok=True)
                content = item.read_bytes()
                dest.write_bytes(content)

            elif item.is_dir():
                # Skip __pycache__
                if item.name == "__pycache__":
                    continue

                dest.mkdir(parents=True, exist_ok=True)
                self._copy_traversable(item, dest, overwrite)

    def get_observability_compose_path(self) -> Path:
        """Get the expected path of the observability compose overlay.

        Returns:
            Path where the observability compose file would be deployed.
        """
        return self.target_dir / "observability" / "docker-compose.observability.yaml"

    def get_observability_k8s_path(self) -> Path:
        """Get the expected path of the K8s observability manifests.

        Returns:
            Path where the K8s observability manifests would be deployed.
        """
        return self.target_dir / "k8s" / "observability"
