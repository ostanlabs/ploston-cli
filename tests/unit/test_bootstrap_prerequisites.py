"""Unit tests for bootstrap prerequisites module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from ploston_cli.bootstrap import (
    DockerDetector,
    ImageResolver,
    KubectlDetector,
    PortScanner,
)


class TestDockerDetector:
    """Tests for DockerDetector."""

    def test_detect_docker_available(self):
        """Test detection when Docker is available."""
        with patch("shutil.which", return_value="/usr/bin/docker"):
            with patch("subprocess.run") as mock_run:
                # Mock docker version
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout="24.0.7",
                )
                detector = DockerDetector()
                info = detector.detect()

                assert info.docker_available is True
                assert "24.0.7" in info.docker_version

    def test_detect_docker_not_available(self):
        """Test detection when Docker is not installed."""
        with patch("shutil.which", return_value=None):
            detector = DockerDetector()
            info = detector.detect()

            assert info.docker_available is False
            assert info.error is not None

    def test_detect_compose_available(self):
        """Test detection of Docker Compose."""
        with patch("shutil.which", return_value="/usr/bin/docker"):
            with patch("subprocess.run") as mock_run:

                def side_effect(cmd, *args, **kwargs):
                    result = MagicMock(returncode=0)
                    if "compose" in cmd:
                        result.stdout = "v2.21.0"
                    else:
                        result.stdout = "24.0.7"
                    return result

                mock_run.side_effect = side_effect
                detector = DockerDetector()
                info = detector.detect()

                assert info.compose_available is True
                assert "2.21.0" in info.compose_version


class TestPortScanner:
    """Tests for PortScanner."""

    def test_check_ports_available(self):
        """Test checking available ports."""
        scanner = PortScanner()
        # Use high ports that are unlikely to be in use
        result = scanner.check_ports({59999: "test"})
        assert len(result) == 1
        assert result[0].port == 59999
        assert result[0].available is True

    def test_suggest_alternative(self):
        """Test suggesting alternative ports."""
        scanner = PortScanner()
        alt = scanner.suggest_alternative(8082)
        # Should suggest a port >= 8083
        assert alt >= 8083


class TestImageResolver:
    """Tests for ImageResolver."""

    def test_resolve_with_tag(self):
        """Test resolving image with explicit tag."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            resolver = ImageResolver()
            result = resolver.resolve("ghcr.io/ostanlabs/ploston-dev", tag="v1.0.0")

            assert result.image == "ghcr.io/ostanlabs/ploston-dev"
            assert result.tag == "v1.0.0"

    def test_resolve_default_tag(self):
        """Test resolving image with default tag."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            resolver = ImageResolver()
            result = resolver.resolve("ghcr.io/ostanlabs/ploston-dev")

            assert result.tag == "latest"


class TestKubectlDetector:
    """Tests for KubectlDetector."""

    def test_detect_kubectl_available(self):
        """Test detection when kubectl is available."""
        with patch("shutil.which", return_value="/usr/bin/kubectl"):
            with patch("subprocess.run") as mock_run:

                def side_effect(cmd, *args, **kwargs):
                    result = MagicMock(returncode=0)
                    if "version" in cmd:
                        result.stdout = "v1.28.0"
                    elif "current-context" in cmd:
                        result.stdout = "minikube"
                    return result

                mock_run.side_effect = side_effect
                detector = KubectlDetector()
                info = detector.detect()

                assert info.kubectl_available is True
                assert "1.28.0" in info.kubectl_version

    def test_detect_kubectl_not_available(self):
        """Test detection when kubectl is not installed."""
        with patch("shutil.which", return_value=None):
            detector = KubectlDetector()
            info = detector.detect()

            assert info.kubectl_available is False
            assert info.error is not None

    def test_detect_no_cluster(self):
        """Test detection when no cluster is configured."""
        with patch("shutil.which", return_value="/usr/bin/kubectl"):
            with patch("subprocess.run") as mock_run:

                def side_effect(cmd, *args, **kwargs):
                    result = MagicMock()
                    if "version" in cmd:
                        result.returncode = 0
                        result.stdout = "v1.28.0"
                    elif "current-context" in cmd:
                        result.returncode = 1
                        result.stdout = ""
                    return result

                mock_run.side_effect = side_effect
                detector = KubectlDetector()
                info = detector.detect()

                assert info.kubectl_available is True
                assert info.cluster_reachable is False
