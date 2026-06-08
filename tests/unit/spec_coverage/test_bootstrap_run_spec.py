"""Specification-driven tests for ``_run_bootstrap`` (commands/bootstrap.py).

``_run_bootstrap`` is the async orchestration core of ``ploston bootstrap``.
These tests drive it directly via ``asyncio.run`` with every external boundary
mocked (state manager, docker/kubectl detectors, port scanner, network
resolver, compose/k8s generators, stack/kubectl deployers, health poller,
auto-chain detector, runner auto-start, debug log). No real Docker, network,
or filesystem side effects occur.

Contract reference: the bootstrap step sequence and its early-return error
paths as documented in the command docstring and step comments.

DISCIPLINE: assertions encode the intended step ordering, the returned
``BootstrapResult`` (success flag, port, cp_url, error), and the documented
early-exit behavior — not incidental output strings beyond the contract.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import ploston_cli.commands.bootstrap as bs

# ---------------------------------------------------------------------------
# Boundary stand-ins
# ---------------------------------------------------------------------------


@dataclass
class _Img:
    ploston_image: str = "ghcr.io/ostanlabs/ploston:latest"
    native_tools_image: str = "ghcr.io/ostanlabs/native-tools:latest"
    build_from_source: bool = False
    should_pull: bool = True


@dataclass
class _State:
    needs_cleanup: bool = False
    stack_running: bool = False
    running_services: list = field(default_factory=list)
    stale_artifacts: list = field(default_factory=list)


@dataclass
class _Health:
    healthy: bool = True
    version: str | None = "1.2.3"
    elapsed_seconds: float = 1.0
    error: str | None = None


@dataclass
class _Port:
    port: int
    available: bool = True
    service_name: str | None = None


def _docker_ok():
    return MagicMock(
        docker_available=True,
        docker_version="27.0",
        compose_available=True,
        compose_version="2.30",
        error=None,
    )


def _net_ok():
    return bs.NetworkResolution(
        proceed=True, network_name="ploston-network", network_external=False
    )


def _patch_blog():
    """Patch the file-backed debug log so no files are written."""
    blog = MagicMock()
    blog.init.return_value = "/tmp/ploston-debug.log"
    return patch.object(bs, "blog", blog)


def _run(**kwargs):
    """Invoke _run_bootstrap with sensible defaults."""
    params = dict(
        target="docker",
        images=_Img(),
        port=8022,
        with_observability=False,
    )
    params.update(kwargs)
    return asyncio.run(bs._run_bootstrap(**params))


# ---------------------------------------------------------------------------
# Common patch context for a clean docker happy-path.
# ---------------------------------------------------------------------------


def _docker_happy_patches(
    *,
    state=None,
    health=None,
    up=(True, "started"),
    ports=None,
    chain=None,
):
    state = state or _State()
    health = health or _Health()
    ports = ports if ports is not None else [_Port(8022), _Port(6379)]

    sm = MagicMock()
    sm.detect_state.return_value = state

    stack = MagicMock()
    stack.up.return_value = up
    stack.compose_files = ["/x/docker-compose.yaml"]

    scanner = MagicMock()
    scanner.check_ports.return_value = ports
    scanner.suggest_alternative.return_value = 8023

    poller = MagicMock()
    poller.wait_for_healthy = AsyncMock(return_value=health)

    chain = chain if chain is not None else MagicMock(configs_found=False)
    chain_det = MagicMock()
    chain_det.detect.return_value = chain

    vol = MagicMock()
    vol.seed_workflows.return_value = []

    gen = MagicMock()
    gen.generate.return_value = "/x/docker-compose.yaml"

    ctxs = [
        _patch_blog(),
        patch.object(bs, "BootstrapStateManager", return_value=sm),
        patch.object(bs, "DockerDetector", return_value=MagicMock(detect=lambda: _docker_ok())),
        patch.object(bs, "PortScanner", return_value=scanner),
        patch.object(bs, "_handle_network_conflict", return_value=_net_ok()),
        patch.object(bs, "ComposeConfig"),
        patch.object(bs, "ComposeGenerator", return_value=gen),
        patch.object(bs, "VolumeManager", return_value=vol),
        patch.object(bs, "AssetManager"),
        patch.object(bs, "save_stack_config"),
        patch.object(bs, "StackManager", return_value=stack),
        patch.object(bs, "HealthPoller", return_value=poller),
        patch.object(bs, "AutoChainDetector", return_value=chain_det),
        patch.object(bs, "_restore_injected_configs"),
    ]
    return ctxs, {"sm": sm, "stack": stack, "scanner": scanner}


class _Multi:
    """Enter/exit a list of context managers as one block."""

    def __init__(self, ctxs):
        self.ctxs = ctxs

    def __enter__(self):
        for c in self.ctxs:
            c.__enter__()
        return self

    def __exit__(self, *a):
        for c in reversed(self.ctxs):
            c.__exit__(*a)
        return False


# ===========================================================================
# Docker happy path
# ===========================================================================


class TestDockerHappyPath:
    def test_clean_install_returns_success_with_cp_url(self):
        ctxs, h = _docker_happy_patches()
        with _Multi(ctxs):
            result = _run()
        assert result.success is True
        assert result.port == 8022
        assert result.cp_url == "http://localhost:8022"
        assert result.error is None
        # The stack must be brought up exactly once, pulling release images.
        h["stack"].up.assert_called_once_with(pull=True)

    def test_skip_import_does_not_run_chain_detection(self):
        ctxs, h = _docker_happy_patches()
        # Capture AutoChainDetector usage.
        chain_det = MagicMock()
        with _Multi(ctxs), patch.object(bs, "AutoChainDetector", return_value=chain_det):
            result = _run(skip_import=True)
        assert result.success is True
        chain_det.detect.assert_not_called()

    def test_local_images_are_not_pulled(self):
        ctxs, h = _docker_happy_patches()
        with _Multi(ctxs):
            result = _run(images=_Img(should_pull=False))
        assert result.success is True
        h["stack"].up.assert_called_once_with(pull=False)


# ===========================================================================
# Prerequisite failures (docker)
# ===========================================================================


class TestDockerPrerequisites:
    def test_docker_unavailable_returns_failure(self):
        sm = MagicMock()
        sm.detect_state.return_value = _State()
        bad = MagicMock(docker_available=False, error="Docker not found", compose_available=False)
        with (
            _patch_blog(),
            patch.object(bs, "BootstrapStateManager", return_value=sm),
            patch.object(bs, "DockerDetector", return_value=MagicMock(detect=lambda: bad)),
        ):
            result = _run()
        assert result.success is False
        assert result.error == "Docker not found"

    def test_compose_unavailable_returns_failure(self):
        sm = MagicMock()
        sm.detect_state.return_value = _State()
        no_compose = MagicMock(
            docker_available=True,
            docker_version="27.0",
            compose_available=False,
            error=None,
        )
        with (
            _patch_blog(),
            patch.object(bs, "BootstrapStateManager", return_value=sm),
            patch.object(bs, "DockerDetector", return_value=MagicMock(detect=lambda: no_compose)),
        ):
            result = _run()
        assert result.success is False
        assert result.error == "Docker Compose not available"


# ===========================================================================
# Stack up / health failures
# ===========================================================================


class TestDeployAndHealthFailures:
    def test_stack_up_failure_returns_error(self):
        ctxs, h = _docker_happy_patches(up=(False, "manifest unknown"))
        with _Multi(ctxs):
            result = _run()
        assert result.success is False
        assert result.error == "manifest unknown"

    def test_health_timeout_returns_error(self):
        ctxs, h = _docker_happy_patches(
            health=_Health(healthy=False, version=None, error="timeout")
        )
        with _Multi(ctxs):
            result = _run()
        assert result.success is False
        assert result.error == "timeout"


# ===========================================================================
# Port-in-use handling (non-interactive does not prompt)
# ===========================================================================


class TestPortHandling:
    def test_non_interactive_ignores_busy_port_and_continues(self):
        """In non-interactive mode a busy port is not auto-changed nor aborted."""
        ctxs, h = _docker_happy_patches(
            ports=[_Port(8022, available=False, service_name="other"), _Port(6379)]
        )
        with _Multi(ctxs):
            result = _run(non_interactive=True)
        # Contract: non-interactive proceeds; suggest_alternative is not consulted.
        assert result.success is True
        h["scanner"].suggest_alternative.assert_not_called()


# ===========================================================================
# Existing state — non-interactive
# ===========================================================================


class TestExistingStateNonInteractive:
    def test_running_healthy_stack_is_reused(self):
        """Non-interactive + running stack + healthy CP → reuse, no redeploy."""
        state = _State(needs_cleanup=True, stack_running=True, running_services=["cp"])
        ctxs, h = _docker_happy_patches(state=state, health=_Health(healthy=True))
        with _Multi(ctxs):
            result = _run(non_interactive=True)
        assert result.success is True
        # Reuse path returns before bringing the stack up.
        h["stack"].up.assert_not_called()

    def test_running_unhealthy_stack_is_torn_down_then_rebuilt(self):
        """Running but unhealthy CP → teardown, then full bootstrap proceeds."""
        state = _State(needs_cleanup=True, stack_running=True, running_services=["cp"])
        # First health poll (quick check) unhealthy; final poll healthy.
        unhealthy = _Health(healthy=False, error="down")
        healthy = _Health(healthy=True)
        ctxs, h = _docker_happy_patches(state=state)
        h["sm"].execute_action.return_value = (True, "torn down")
        poller = MagicMock()
        poller.wait_for_healthy = AsyncMock(side_effect=[unhealthy, healthy])
        with _Multi(ctxs), patch.object(bs, "HealthPoller", return_value=poller):
            result = _run(non_interactive=True)
        assert result.success is True
        h["sm"].execute_action.assert_called_once()
        h["stack"].up.assert_called_once()

    def test_teardown_failure_during_cleanup_aborts(self):
        state = _State(needs_cleanup=True, stack_running=True, running_services=["cp"])
        ctxs, h = _docker_happy_patches(state=state, health=_Health(healthy=False, error="down"))
        h["sm"].execute_action.return_value = (False, "teardown failed")
        with _Multi(ctxs):
            result = _run(non_interactive=True)
        assert result.success is False
        assert result.error == "teardown failed"

    def test_stale_artifacts_no_running_stack_cleaned_up(self):
        """Non-interactive + stale artifacts (stack down) → auto teardown, proceed."""
        state = _State(needs_cleanup=True, stack_running=False, stale_artifacts=["net"])
        ctxs, h = _docker_happy_patches(state=state)
        h["sm"].execute_action.return_value = (True, "cleaned")
        with _Multi(ctxs):
            result = _run(non_interactive=True)
        assert result.success is True
        h["sm"].execute_action.assert_called_once()
        h["stack"].up.assert_called_once()


# ===========================================================================
# Network resolution abort
# ===========================================================================


class TestNetworkResolution:
    def test_network_cancelled_aborts_bootstrap(self):
        ctxs, h = _docker_happy_patches()
        with (
            _Multi(ctxs),
            patch.object(
                bs,
                "_handle_network_conflict",
                return_value=bs.NetworkResolution(proceed=False, error="Cancelled by user"),
            ),
        ):
            result = _run()
        assert result.success is False
        assert result.error == "Cancelled by user"
        # Must not deploy after a cancelled network step.
        h["stack"].up.assert_not_called()


# ===========================================================================
# Build-from-source path
# ===========================================================================


class TestBuildFromSource:
    def test_build_failure_when_not_in_workspace(self):
        ctxs, h = _docker_happy_patches()
        with _Multi(ctxs), patch.object(bs, "detect_meta_repo_root", return_value=None):
            result = _run(images=_Img(build_from_source=True, should_pull=False))
        assert result.success is False
        assert "development workspace" in (result.error or "")
        h["stack"].up.assert_not_called()

    def test_build_success_continues_to_deploy(self, tmp_path):
        ctxs, h = _docker_happy_patches()
        with (
            _Multi(ctxs),
            patch.object(bs, "detect_meta_repo_root", return_value=tmp_path),
            patch.object(bs, "build_from_source", return_value=("ploston:local", "native:local")),
        ):
            result = _run(images=_Img(build_from_source=True, should_pull=False))
        assert result.success is True
        h["stack"].up.assert_called_once_with(pull=False)

    def test_build_error_returns_failure(self, tmp_path):
        ctxs, h = _docker_happy_patches()
        with (
            _Multi(ctxs),
            patch.object(bs, "detect_meta_repo_root", return_value=tmp_path),
            patch.object(bs, "build_from_source", side_effect=bs.BuildError("compile failed")),
        ):
            result = _run(images=_Img(build_from_source=True, should_pull=False))
        assert result.success is False
        assert result.error == "compile failed"


# ===========================================================================
# Kubernetes path
# ===========================================================================


def _k8s_patches(*, kubectl=None, apply_result=(True, "applied"), health=None):
    sm = MagicMock()
    sm.detect_state.return_value = _State()

    scanner = MagicMock()
    scanner.check_ports.return_value = [_Port(8022), _Port(6379)]

    poller = MagicMock()
    poller.wait_for_healthy = AsyncMock(return_value=health or _Health())

    if kubectl is None:
        kubectl = MagicMock(
            kubectl_available=True,
            kubectl_version="1.30",
            cluster_reachable=True,
            cluster_info="minikube",
            error=None,
        )
    k8s_gen = MagicMock()
    k8s_gen.generate.return_value = "/k8s/manifests"

    deployer = MagicMock()
    deployer.apply.return_value = apply_result

    chain_det = MagicMock()
    chain_det.detect.return_value = MagicMock(configs_found=False)

    return [
        _patch_blog(),
        patch.object(bs, "BootstrapStateManager", return_value=sm),
        patch.object(bs, "KubectlDetector", return_value=MagicMock(detect=lambda: kubectl)),
        patch.object(bs, "PortScanner", return_value=scanner),
        patch.object(bs, "K8sConfig"),
        patch.object(bs, "K8sManifestGenerator", return_value=k8s_gen),
        patch.object(bs, "KubectlDeployer", return_value=deployer),
        patch.object(bs, "HealthPoller", return_value=poller),
        patch.object(bs, "AutoChainDetector", return_value=chain_det),
    ], deployer


class TestKubernetesPath:
    def test_k8s_happy_path_applies_manifests(self):
        ctxs, deployer = _k8s_patches()
        with _Multi(ctxs):
            result = _run(target="k8s", skip_import=True)
        assert result.success is True
        deployer.apply.assert_called_once()

    def test_kubectl_unavailable_aborts(self):
        bad = MagicMock(kubectl_available=False, error="kubectl missing")
        ctxs, _ = _k8s_patches(kubectl=bad)
        with _Multi(ctxs):
            result = _run(target="k8s")
        assert result.success is False
        assert result.error == "kubectl missing"

    def test_no_cluster_aborts(self):
        bad = MagicMock(
            kubectl_available=True,
            kubectl_version="1.30",
            cluster_reachable=False,
            error=None,
        )
        ctxs, _ = _k8s_patches(kubectl=bad)
        with _Multi(ctxs):
            result = _run(target="k8s")
        assert result.success is False
        assert result.error == "No K8s cluster available"

    def test_apply_failure_returns_error(self):
        ctxs, deployer = _k8s_patches(apply_result=(False, "apply rejected"))
        with _Multi(ctxs):
            result = _run(target="k8s", skip_import=True)
        assert result.success is False
        assert result.error == "apply rejected"


# ===========================================================================
# Auto-chain / import path (non-interactive)
# ===========================================================================


class TestExistingStateInteractive:
    def test_keep_running_choice_returns_without_redeploy(self):
        """Interactive choice [1] Keep running → success, no teardown / up."""
        state = _State(needs_cleanup=True, stack_running=True, running_services=["cp"])
        ctxs, h = _docker_happy_patches(state=state)
        with _Multi(ctxs), patch.object(bs.click, "prompt", return_value="1"):
            result = _run(non_interactive=False)
        assert result.success is True
        h["stack"].up.assert_not_called()
        h["sm"].execute_action.assert_not_called()

    def test_restart_choice_returns_after_action(self):
        """Interactive choice [2] Restart → execute_action(RESTART), then return."""
        state = _State(needs_cleanup=True, stack_running=True, running_services=["cp"])
        ctxs, h = _docker_happy_patches(state=state)
        h["sm"].execute_action.return_value = (True, "restarted")
        with _Multi(ctxs), patch.object(bs.click, "prompt", return_value="2"):
            result = _run(non_interactive=False)
        assert result.success is True
        action = h["sm"].execute_action.call_args[0][0]
        assert action is bs.BootstrapAction.RESTART
        # RESTART path returns early — does not fall through to a fresh `up`.
        h["stack"].up.assert_not_called()

    def test_teardown_choice_falls_through_to_full_bootstrap(self):
        """Interactive choice [4] Teardown → teardown then full deploy."""
        state = _State(needs_cleanup=True, stack_running=True, running_services=["cp"])
        ctxs, h = _docker_happy_patches(state=state)
        h["sm"].execute_action.return_value = (True, "torn down")
        # prompt is called twice: option select (4) then telemetry preserve (Y).
        with _Multi(ctxs), patch.object(bs.click, "prompt", side_effect=["4", "Y"]):
            result = _run(non_interactive=False)
        assert result.success is True
        action = h["sm"].execute_action.call_args[0][0]
        assert action is bs.BootstrapAction.TEARDOWN
        h["stack"].up.assert_called_once()

    def test_stale_artifacts_interactive_continue_without_cleaning(self):
        """Stack down + artifacts, choice [2] Continue → no teardown, proceed."""
        state = _State(needs_cleanup=True, stack_running=False, stale_artifacts=["net"])
        ctxs, h = _docker_happy_patches(state=state)
        with _Multi(ctxs), patch.object(bs.click, "prompt", return_value="2"):
            result = _run(non_interactive=False)
        assert result.success is True
        h["sm"].execute_action.assert_not_called()
        h["stack"].up.assert_called_once()


class TestObservability:
    def test_observability_deploys_assets_and_merges_env(self):
        """--with-observability deploys assets and runs grafana cleanup."""
        ctxs, h = _docker_happy_patches()
        with (
            _Multi(ctxs),
            patch("ploston_cli.init.env_manager.merge_env_file") as merge,
            patch(
                "ploston_cli.bootstrap.grafana_cleanup.cleanup_orphaned_grafana_datasources",
                return_value=0,
            ) as cleanup,
        ):
            result = _run(with_observability=True)
        assert result.success is True
        merge.assert_called_once()
        cleanup.assert_called_once()


class TestAutoChainImport:
    def test_servers_found_imports_and_starts_runner(self):
        srv = MagicMock(source="claude_desktop")
        chain = MagicMock(
            configs_found=True,
            total_servers=1,
            server_names=["filesystem"],
            servers={"filesystem": srv},
            detected_configs=[],
        )
        ctxs, h = _docker_happy_patches(chain=chain)

        selector = MagicMock()
        selector.select_all.return_value = ["filesystem"]

        runner_obj = MagicMock()
        runner_obj.start_runner.return_value = (True, "ok")

        with (
            _Multi(ctxs),
            patch.object(bs, "ServerSelector", return_value=selector),
            patch.object(bs, "RunnerAutoStart", return_value=runner_obj),
            patch(
                "ploston_cli.commands.init._complete_import_flow",
                new=AsyncMock(return_value=None),
            ),
        ):
            result = _run(non_interactive=True)
        assert result.success is True
        selector.select_all.assert_called_once()
        runner_obj.start_runner.assert_called_once_with(daemon=True)

    def test_no_servers_selected_skips_import(self):
        srv = MagicMock(source="claude_desktop")
        chain = MagicMock(
            configs_found=True,
            total_servers=1,
            server_names=["filesystem"],
            servers={"filesystem": srv},
            detected_configs=[],
        )
        ctxs, h = _docker_happy_patches(chain=chain)
        selector = MagicMock()
        selector.select_all.return_value = []
        runner_obj = MagicMock()
        with (
            _Multi(ctxs),
            patch.object(bs, "ServerSelector", return_value=selector),
            patch.object(bs, "RunnerAutoStart", return_value=runner_obj),
        ):
            result = _run(non_interactive=True)
        assert result.success is True
        runner_obj.start_runner.assert_not_called()
