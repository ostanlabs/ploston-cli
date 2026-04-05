"""Bootstrap command for deploying Ploston Control Plane.

This module provides the `ploston bootstrap` command which deploys
the Control Plane stack to Docker Compose or Kubernetes.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass

import click

from ..bootstrap import (
    AssetManager,
    AutoChainDetector,
    BootstrapAction,
    BootstrapStateManager,
    ComposeConfig,
    ComposeGenerator,
    DockerDetector,
    HealthPoller,
    K8sConfig,
    K8sIngressHost,
    K8sManifestGenerator,
    KubectlDeployer,
    KubectlDetector,
    NetworkManager,
    PortScanner,
    RunnerAutoStart,
    StackManager,
    StackState,
    VolumeManager,
    save_stack_config,
)
from ..bootstrap import bootstrap_log as blog
from ..bootstrap.builder import BuildError, build_from_source
from ..bootstrap.image_resolver import ImageConfig, ImageResolverError, resolve_images
from ..bootstrap.workspace import detect_meta_repo_root
from ..init import ServerSelector
from ..init.detector import ConfigDetector
from ..init.injector import is_already_injected, restore_config_from_imported

DEFAULT_NETWORK_NAME = "ploston-network"


def _restore_injected_configs() -> None:
    """Detect and restore any Claude/Cursor configs that were injected by Ploston.

    Scans for known config files, checks if Ploston bridge entries are present,
    and restores from the inline ``_ploston_imported`` section automatically.
    """
    detector = ConfigDetector()
    configs = detector.detect_all()

    for config in configs:
        if not config.path or not config.path.exists():
            continue
        if not is_already_injected(config.path):
            continue

        label = "Claude Desktop" if config.source == "claude_desktop" else "Cursor"
        if restore_config_from_imported(config.path):
            click.echo(f"  ✓ Restored {label} config from _ploston_imported")
        else:
            click.echo(f"  ⚠ {label} config has Ploston entries but could not be restored.")


def _prompt_preserve_telemetry() -> bool:
    """Prompt the user whether to preserve telemetry and workflow data during teardown.

    Returns:
        True to preserve, False to wipe.
    """
    answer = click.prompt(
        "\n  Preserve telemetry data and registered workflows from previous installation?",
        default="Y",
        show_default=True,
    )
    preserve = answer.strip().lower() not in ("no", "n")
    if not preserve:
        click.echo("  Telemetry data and registered workflows will be cleared.")
    else:
        click.echo("  Telemetry data and registered workflows will be preserved.")
    return preserve


@dataclass
class BootstrapResult:
    """Result of bootstrap execution."""

    success: bool
    port: int = 8022
    cp_url: str = "http://localhost:8022"
    error: str | None = None


@dataclass
class NetworkResolution:
    """Result of network conflict resolution."""

    proceed: bool = True
    network_name: str = DEFAULT_NETWORK_NAME
    network_external: bool = False
    error: str | None = None


def _handle_network_conflict(
    network_name: str,
    non_interactive: bool,
) -> NetworkResolution:
    """Check for and handle network conflicts.

    Args:
        network_name: Name of the network to check.
        non_interactive: If True, auto-resolve conflicts.

    Returns:
        NetworkResolution with the resolved network configuration.
    """
    net_manager = NetworkManager(network_name)
    conflict = net_manager.check_network_exists()

    if not conflict.exists:
        # No conflict, proceed normally
        return NetworkResolution(
            proceed=True,
            network_name=network_name,
            network_external=False,
        )

    # Network exists - show info
    click.echo(f"\n⚠️  Network '{network_name}' already exists")

    if conflict.network_info:
        info = conflict.network_info
        click.echo(f"   ID: {info.id}")
        click.echo(f"   Driver: {info.driver}")
        if info.containers:
            click.echo(f"   Containers: {', '.join(info.containers)}")
        else:
            click.echo("   Containers: (none)")

    # Check for service conflicts
    service_conflicts = net_manager.check_service_conflicts()
    if service_conflicts:
        click.echo(f"\n   ⚠️  Conflicting services: {', '.join(service_conflicts)}")

    if non_interactive:
        # In non-interactive mode, try to use the existing network
        click.echo("\n   Using existing network (non-interactive mode)")
        return NetworkResolution(
            proceed=True,
            network_name=network_name,
            network_external=True,
        )

    # Interactive mode - ask user
    click.echo("\nOptions:")
    click.echo("  [1] Remove network and recreate")
    if service_conflicts:
        click.echo("      ⚠️  This will stop conflicting containers")
    click.echo("  [2] Use existing network")
    if service_conflicts:
        click.echo("      ⚠️  Existing services will be replaced")
    alt_name = net_manager.suggest_alternative_name()
    click.echo(f"  [3] Deploy to different network ({alt_name})")
    click.echo("  [4] Cancel")

    choice = click.prompt(
        "Select option",
        type=click.Choice(["1", "2", "3", "4"]),
        default="2",
    )

    if choice == "1":
        # Remove network
        if service_conflicts:
            if not click.confirm(
                f"This will stop containers: {', '.join(service_conflicts)}. Continue?"
            ):
                return NetworkResolution(proceed=False, error="Cancelled by user")

        click.echo(f"   Removing network '{network_name}'...")
        success, msg = net_manager.remove_network(force=True)
        if not success:
            click.echo(f"   ✗ {msg}")
            return NetworkResolution(proceed=False, error=msg)
        click.echo(f"   ✓ {msg}")
        return NetworkResolution(
            proceed=True,
            network_name=network_name,
            network_external=False,
        )

    elif choice == "2":
        # Use existing network
        if service_conflicts:
            if not click.confirm(
                f"Services {', '.join(service_conflicts)} will be replaced. Continue?"
            ):
                return NetworkResolution(proceed=False, error="Cancelled by user")
        return NetworkResolution(
            proceed=True,
            network_name=network_name,
            network_external=True,
        )

    elif choice == "3":
        # Use alternative network name
        return NetworkResolution(
            proceed=True,
            network_name=alt_name,
            network_external=False,
        )

    else:
        # Cancel
        return NetworkResolution(proceed=False, error="Cancelled by user")


@click.group(invoke_without_command=True)
@click.option(
    "--target",
    type=click.Choice(["docker", "k8s"]),
    default="docker",
    help="Deployment target",
)
@click.option("--image-tag", default=None, help="Docker image tag (e.g., v1.0.0, sha-abc1234)")
@click.option(
    "--edge",
    is_flag=True,
    help="Use latest tested dev images (ghcr.io/ostanlabs/ploston-dev:edge)",
)
@click.option(
    "--pre-release",
    is_flag=True,
    hidden=True,  # Hidden — kept for backward compat, not shown in help
    help="Deprecated: use --edge",
)
@click.option(
    "--build-from-source",
    is_flag=True,
    help="Build images from local source (requires meta-repo)",
)
@click.option("--port", default=8022, type=int, help="CP port")
@click.option(
    "--with-observability",
    is_flag=True,
    help="Include Prometheus + Grafana + Loki",
)
@click.option(
    "--with-native-tools",
    is_flag=True,
    help="Include native-tools MCP server (disabled by default)",
)
@click.option("--no-import", is_flag=True, help="Skip auto-detection and import chaining")
@click.option("--non-interactive", "-y", is_flag=True, help="Accept all defaults")
@click.option("--kubeconfig", default=None, help="Kubeconfig path (K8s only)")
@click.option("--namespace", default="ploston", help="K8s namespace")
@click.option(
    "--domain",
    default=None,
    help="Base domain for K8s ingress (e.g., ostanlabs.homelab → <namespace>.ostanlabs.homelab)",
)
@click.option("--network", default=DEFAULT_NETWORK_NAME, help="Docker network name")
@click.pass_context
def bootstrap(
    ctx,
    target,
    image_tag,
    edge,
    pre_release,
    build_from_source,
    port,
    with_observability,
    with_native_tools,
    no_import,
    non_interactive,
    kubeconfig,
    namespace,
    domain,
    network,
):
    """Deploy the Ploston Control Plane.

    This command deploys the Ploston Control Plane stack to Docker Compose
    (default) or Kubernetes. It handles prerequisites, generates configuration,
    starts services, and waits for the CP to become healthy.

    Image resolution:

        Default:                  ghcr.io/ostanlabs/ploston:latest

        --edge:                   ghcr.io/ostanlabs/ploston-dev:edge

        --edge --image-tag TAG:   ghcr.io/ostanlabs/ploston-dev:TAG

        --image-tag TAG:          ghcr.io/ostanlabs/ploston:TAG

        --build-from-source:      ploston:local (built locally)

    Examples:

        # Developer daily driver — latest tested image
        ploston bootstrap --edge

        # Deploy with observability stack (dev)
        ploston bootstrap --edge --with-observability

        # Release image (requires production release to exist)
        ploston bootstrap

        # Specific image tag
        ploston bootstrap --edge --image-tag sha-abc1234

        # Build from local source
        ploston bootstrap --build-from-source

        # Deploy to Kubernetes
        ploston bootstrap --target k8s --namespace ploston

        # Deploy to K8s with native-tools and ingress
        ploston bootstrap --target k8s --with-native-tools --domain ostanlabs.homelab
    """
    if ctx.invoked_subcommand is not None:
        return  # Subcommand handles it

    # Backward compat: --pre-release is deprecated alias for --edge
    if pre_release and not edge:
        click.echo(
            "Warning: --pre-release is deprecated. Use --edge instead.",
            err=True,
        )
        edge = True

    # Resolve images early to fail fast on invalid flag combinations
    try:
        images = resolve_images(
            image_tag=image_tag,
            edge=edge,
            build_from_source=build_from_source,
        )
    except ImageResolverError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    asyncio.run(
        _run_bootstrap(
            target=target,
            images=images,
            port=port,
            with_observability=with_observability,
            with_native_tools=with_native_tools,
            skip_import=no_import,
            non_interactive=non_interactive,
            kubeconfig=kubeconfig,
            namespace=namespace,
            domain=domain,
            network_name=network,
        )
    )


@bootstrap.command()
def status():
    """Show current stack status."""
    from ..runner.daemon import is_running as runner_is_running

    manager = StackManager()
    stack_status = manager.status()

    if stack_status.state == StackState.NOT_FOUND:
        click.echo("No Ploston stack found. Run: ploston bootstrap")
        return

    click.echo(f"Stack state: {stack_status.state.value}")

    # ── Service table with ports ──
    if stack_status.service_details:
        click.echo("\nServices:")
        for svc in stack_status.service_details:
            if svc.state == "running":
                icon = "✓"
                health_tag = f" ({svc.health})" if svc.health else ""
            else:
                icon = "✗"
                health_tag = ""
            ports_str = ", ".join(f":{p}" for p in svc.ports) if svc.ports else ""
            line = f"  {icon} {svc.name}"
            if ports_str:
                line += f"  {ports_str}"
            line += health_tag
            click.echo(line)
    else:
        # Fallback to simple lists when details aren't available
        if stack_status.running_services:
            click.echo("Running services:")
            for svc in stack_status.running_services:
                click.echo(f"  ✓ {svc}")
        if stack_status.stopped_services:
            click.echo("Stopped services:")
            for svc in stack_status.stopped_services:
                click.echo(f"  ✗ {svc}")

    # ── Endpoints summary ──
    endpoints: list[tuple[str, str]] = []
    for svc in stack_status.service_details:
        if svc.state != "running" or not svc.ports:
            continue
        for port in svc.ports:
            endpoints.append((svc.name, f"http://localhost:{port}"))

    if endpoints:
        click.echo("\nEndpoints:")
        for name, url in endpoints:
            click.echo(f"  {name:20s} {url}")

    # ── Runner daemon ──
    alive, pid = runner_is_running()
    click.echo("")
    if alive:
        click.echo(f"Runner: running (PID {pid})")
    else:
        click.echo("Runner: not running")


@bootstrap.command()
@click.option("--volumes", is_flag=True, help="Also remove volumes (data loss!)")
@click.option(
    "--target",
    type=click.Choice(["docker", "k8s"]),
    default="docker",
)
@click.option("--namespace", default="ploston")
@click.option("--kubeconfig", default=None)
@click.option(
    "-y", "--non-interactive", is_flag=True, help="Skip prompts (preserve telemetry by default)"
)
def down(volumes, target, namespace, kubeconfig, non_interactive):
    """Stop and remove the Ploston stack."""
    _restore_injected_configs()

    if target == "docker":
        state_manager = BootstrapStateManager()
        if volumes:
            if not non_interactive and not click.confirm(
                "This will delete all Ploston data. Continue?"
            ):
                return
            # --volumes implies wipe everything including telemetry
            preserve_telemetry = False
        elif non_interactive:
            # Non-interactive: preserve telemetry by default
            preserve_telemetry = True
        else:
            # Prompt for telemetry data preservation (DEC-150)
            preserve_telemetry = _prompt_preserve_telemetry()

        success, msg = state_manager.execute_action(
            BootstrapAction.TEARDOWN,
            preserve_telemetry=preserve_telemetry,
        )
        if success:
            click.echo("✓ Ploston stack stopped.")
        else:
            click.echo(f"✗ {msg}", err=True)
            sys.exit(1)
    else:
        deployer = KubectlDeployer(kubeconfig)
        success, msg = deployer.delete_namespace(namespace)
        if success:
            click.echo(f"✓ Namespace '{namespace}' deleted.")
        else:
            click.echo(f"✗ {msg}", err=True)
            sys.exit(1)


@bootstrap.command()
@click.option("--follow", "-f", is_flag=True, help="Follow log output")
@click.option("--service", "-s", default=None, help="Show logs for specific service")
@click.option("--tail", default=100, type=int, help="Number of lines")
def logs(follow, service, tail):
    """Show stack logs."""
    manager = StackManager()
    proc = manager.logs(follow=follow, service=service, tail=tail)
    if proc is not None:
        try:
            proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            proc.wait()


@bootstrap.command()
def restart():
    """Restart the Ploston stack."""
    manager = StackManager()
    success, msg = manager.restart()
    if success:
        click.echo("✓ Stack restarted.")
    else:
        click.echo(f"✗ {msg}", err=True)
        sys.exit(1)


@bootstrap.command("restart-runner")
def restart_runner():
    """Restart the local runner daemon.

    Stops the running runner and starts it again, forcing all MCP child
    processes to be respawned.  This picks up any changes you made to
    local MCP server files (e.g. JS/Python scripts) without having to
    manually stop/start or remember the connection flags.

    The runner credentials (CP URL, token, name) are read from
    ~/.ploston/.env which was written by ``ploston init --import``.
    """
    from ..runner.daemon import is_running, stop_daemon

    # ── 1. Stop if running ──
    alive, pid = is_running()
    if alive:
        click.echo(f"Stopping runner (PID {pid})...")
        stop_daemon()
    else:
        click.echo("Runner is not running.")

    # ── 2. Re-read credentials from ~/.ploston/.env ──
    runner = RunnerAutoStart()  # defaults to http://localhost:8022
    token = runner._get_runner_token()
    if not token:
        click.echo(
            "✗ Runner token not found in ~/.ploston/.env. Run 'ploston init --import' first.",
            err=True,
        )
        sys.exit(1)

    name = runner._get_runner_name()
    ws_url = runner._get_ws_url()

    click.echo(f"Starting runner '{name}'...")
    success, msg = runner.start_runner(daemon=True)
    if success:
        click.echo(f"✓ Runner restarted (name={name}, cp={ws_url}).")
        click.echo("  All MCP child processes have been respawned.")
    else:
        click.echo(f"✗ Failed to restart runner: {msg}", err=True)
        sys.exit(1)


@bootstrap.command()
def rollback():
    """Restore Claude Desktop and Cursor configs to their pre-injection state.

    Scans for configs that were modified by ``ploston init --import --inject``
    and restores them from the inline ``_ploston_imported`` section, which
    holds the original server definitions.

    \b
    This is safe to run at any time — if no injection is detected the command
    is a no-op.
    """
    detector = ConfigDetector()
    configs = detector.detect_all()

    restored = 0
    for config in configs:
        if not config.path or not config.path.exists():
            continue
        if not is_already_injected(config.path):
            continue

        label = "Claude Desktop" if config.source == "claude_desktop" else "Cursor"
        if restore_config_from_imported(config.path):
            click.echo(f"  ✓ Restored {label} config from _ploston_imported")
            restored += 1
        else:
            click.echo(
                f"  ⚠ {label} config has Ploston entries but could not be restored.\n"
                f"    Check: {config.path}"
            )

    if restored:
        click.echo(f"\n✓ {restored} config(s) restored. Restart Claude Desktop / Cursor to apply.")
    elif not any(
        config.path and config.path.exists() and is_already_injected(config.path)
        for config in configs
    ):
        click.echo("No injected configs found — nothing to roll back.")


async def _run_bootstrap(
    target: str,
    images: ImageConfig,
    port: int,
    with_observability: bool,
    with_native_tools: bool = False,
    skip_import: bool = False,
    non_interactive: bool = False,
    kubeconfig: str | None = None,
    namespace: str = "ploston",
    domain: str | None = None,
    network_name: str = DEFAULT_NETWORK_NAME,
) -> BootstrapResult:
    """Execute the full bootstrap flow."""
    # ── Initialise file-based debug log ──
    log_path = blog.init()
    click.echo(f"\n📝 Debug log: {log_path}")

    blog.section("Bootstrap Parameters")
    blog.info("target", target)
    blog.info("images.ploston_image", images.ploston_image)
    blog.info("images.native_tools_image", images.native_tools_image)
    blog.info("images.should_pull", str(images.should_pull))
    blog.info("images.build_from_source", str(images.build_from_source))
    blog.info("port", str(port))
    blog.info("with_observability", str(with_observability))
    blog.info("with_native_tools", str(with_native_tools))
    blog.info("skip_import", str(skip_import))
    blog.info("non_interactive", str(non_interactive))
    blog.info("network_name", network_name)

    click.echo("\n🚀 Ploston Bootstrap\n")

    # ── Step 1: Check existing state ──
    blog.step("Step 0: Detect existing state")
    state_manager = BootstrapStateManager()
    state = state_manager.detect_state()
    blog.info("needs_cleanup", str(state.needs_cleanup))
    blog.info("stack_running", str(state.stack_running))
    blog.info("running_services", str(state.running_services))
    blog.info("stale_artifacts", str(state.stale_artifacts))

    if state.needs_cleanup:
        if state.stack_running:
            click.echo("📋 Existing Stack Detected\n")
            click.echo(f"  Running services: {', '.join(state.running_services or [])}")
        else:
            click.echo("📋 Stale Artifacts Detected\n")
            for artifact in state.stale_artifacts:
                click.echo(f"  • {artifact}")

        if non_interactive:
            if state.stack_running and not images.build_from_source:
                # Quick health check — only reuse the stack if the CP is actually healthy.
                cp_url = f"http://localhost:{port}"
                poller = HealthPoller(max_attempts=3, interval_seconds=1.0, timeout_seconds=3.0)
                quick_check = await poller.wait_for_healthy(cp_url)
                if quick_check.healthy:
                    click.echo("\n  Using existing stack (non-interactive mode)")
                    return BootstrapResult(success=True, port=port)
                click.echo("\n  Stack services running but CP is unhealthy — recreating...")
            # Auto-teardown: stack running with --build-from-source, or
            # stale artifacts with no running stack.
            # Non-interactive always preserves telemetry data (DEC-150).
            _restore_injected_configs()
            click.echo("\n  Cleaning up before fresh bootstrap...")
            success, msg = state_manager.execute_action(
                BootstrapAction.TEARDOWN,
                preserve_telemetry=True,
            )
            if not success:
                click.echo(f"\n✗ {msg}", err=True)
                return BootstrapResult(success=False, error=msg)
            click.echo(f"  ✓ {msg}")
            # Fall through to full bootstrap flow below
        elif state.stack_running:
            if images.build_from_source:
                recreate_label = "Recreate stack (rebuild from source)"
            else:
                recreate_label = "Recreate stack (pull latest images)"
            click.echo("\nOptions:")
            click.echo("  [1] Keep running (nothing to do)")
            click.echo("  [2] Restart stack")
            click.echo(f"  [3] {recreate_label}")
            click.echo("  [4] Tear down and re-bootstrap")

            choice = click.prompt(
                "Select option", type=click.Choice(["1", "2", "3", "4"]), default="1"
            )

            action_map = {
                "1": BootstrapAction.KEEP_RUNNING,
                "2": BootstrapAction.RESTART,
                "3": BootstrapAction.RECREATE,
                "4": BootstrapAction.TEARDOWN,
            }
            action = action_map[choice]

            if action == BootstrapAction.KEEP_RUNNING:
                click.echo("\n✓ Stack is running. Nothing to do.")
                return BootstrapResult(success=True, port=port)
            elif action == BootstrapAction.TEARDOWN:
                # Prompt for telemetry data preservation (DEC-150)
                preserve_telemetry = _prompt_preserve_telemetry()
                _restore_injected_configs()
                click.echo("\n  Tearing down existing stack...")
                success, msg = state_manager.execute_action(
                    action,
                    preserve_telemetry=preserve_telemetry,
                )
                if not success:
                    click.echo(f"\n✗ {msg}", err=True)
                    return BootstrapResult(success=False, error=msg)
                click.echo(f"  ✓ {msg}")
                # Fall through to full bootstrap flow below
            else:
                # RESTART or RECREATE — rebuild images first when
                # --build-from-source is active so the stack picks up
                # the latest local code changes.
                if images.build_from_source:
                    click.echo("\n  Rebuilding images from source...")
                    repo_root = detect_meta_repo_root()
                    if repo_root is None:
                        msg = (
                            "Cannot rebuild: not inside the ploston development "
                            "workspace (agent-execution-layer)."
                        )
                        click.echo(f"\n✗ {msg}", err=True)
                        return BootstrapResult(success=False, error=msg)
                    try:
                        ploston_img, native_tools_img = build_from_source(repo_root)
                        click.echo(f"  ✓ Built: {ploston_img}")
                        click.echo(f"  ✓ Built: {native_tools_img}")
                    except BuildError as e:
                        click.echo(f"  ✗ {e}", err=True)
                        return BootstrapResult(success=False, error=str(e))

                success, msg = state_manager.execute_action(
                    action,
                    skip_pull=images.build_from_source,
                )
                if not success:
                    click.echo(f"\n✗ {msg}", err=True)
                    return BootstrapResult(success=False, error=msg)
                click.echo(f"\n✓ {msg}")
                return BootstrapResult(success=True, port=port)
        else:
            # Stack not running but artifacts exist — offer cleanup.
            click.echo("\nOptions:")
            click.echo("  [1] Clean up and re-bootstrap")
            click.echo("  [2] Continue without cleaning")

            choice = click.prompt("Select option", type=click.Choice(["1", "2"]), default="1")

            if choice == "1":
                # Prompt for telemetry data preservation (DEC-150)
                preserve_telemetry = _prompt_preserve_telemetry()
                _restore_injected_configs()
                click.echo("\n  Cleaning up stale artifacts...")
                success, msg = state_manager.execute_action(
                    BootstrapAction.TEARDOWN,
                    preserve_telemetry=preserve_telemetry,
                )
                if not success:
                    click.echo(f"\n✗ {msg}", err=True)
                    return BootstrapResult(success=False, error=msg)
                click.echo(f"  ✓ {msg}")
            # Fall through to full bootstrap flow below

    # ── Step 2: Prerequisites ──
    blog.step("Step 1: Prerequisites")
    click.echo("📋 Step 1: Prerequisites\n")

    if target == "docker":
        docker = DockerDetector().detect()
        if not docker.docker_available:
            click.echo(f"  ✗ Docker: {docker.error}", err=True)
            return BootstrapResult(success=False, error=docker.error)
        click.echo(f"  ✓ Docker: {docker.docker_version}")
        if docker.compose_available:
            click.echo(f"  ✓ Compose: {docker.compose_version}")
        else:
            click.echo("  ✗ Docker Compose not available", err=True)
            return BootstrapResult(success=False, error="Docker Compose not available")
    else:
        kubectl = KubectlDetector().detect()
        if not kubectl.kubectl_available:
            click.echo(f"  ✗ kubectl: {kubectl.error}", err=True)
            return BootstrapResult(success=False, error=kubectl.error)
        click.echo(f"  ✓ kubectl: {kubectl.kubectl_version}")
        if kubectl.cluster_reachable:
            click.echo(f"  ✓ Cluster: {kubectl.cluster_info}")
        else:
            click.echo("  ✗ No cluster available", err=True)
            return BootstrapResult(success=False, error="No K8s cluster available")

    # ── Step 3: Port check ──
    blog.step("Step 2: Port Check")
    click.echo("\n📋 Step 2: Port Check\n")
    scanner = PortScanner()
    port_status = scanner.check_ports({port: "ploston", 6379: "redis"})

    for status in port_status:
        if status.available:
            click.echo(f"  ✓ Port {status.port}: available")
        else:
            click.echo(f"  ✗ Port {status.port}: in use by {status.service_name or 'unknown'}")
            if not non_interactive:
                alt = scanner.suggest_alternative(status.port)
                if alt and click.confirm(f"  Use port {alt} instead?"):
                    if status.port == port:
                        port = alt
                else:
                    return BootstrapResult(success=False, error=f"Port {status.port} in use")

    # ── Step 4: Network check (Docker only) ──
    blog.step("Step 3: Network Check")
    network_external = False
    if target == "docker":
        click.echo("\n📋 Step 3: Network Check\n")
        net_resolution = _handle_network_conflict(network_name, non_interactive)

        if not net_resolution.proceed:
            click.echo(f"  ✗ {net_resolution.error}", err=True)
            return BootstrapResult(success=False, error=net_resolution.error)

        network_name = net_resolution.network_name
        network_external = net_resolution.network_external

        if network_external:
            click.echo(f"  ✓ Using existing network: {network_name}")
        else:
            click.echo(f"  ✓ Will create network: {network_name}")

    # ── Step 4a: Build from source (if requested) ──
    if images.build_from_source:
        blog.step("Step 4a: Build from Source")
        click.echo("\n📋 Step 4a: Build from Source\n")
        repo_root = detect_meta_repo_root()
        if repo_root is None:
            msg = (
                "This requires running inside the ploston development workspace "
                "(agent-execution-layer). Could not find packages/ploston/ + ci/images.yaml "
                "in any parent directory."
            )
            click.echo(f"  ✗ {msg}", err=True)
            return BootstrapResult(success=False, error=msg)

        click.echo(f"  Meta-repo: {repo_root}")
        try:
            ploston_img, native_tools_img = build_from_source(repo_root)
            click.echo(f"  ✓ Built: {ploston_img}")
            click.echo(f"  ✓ Built: {native_tools_img}")
        except BuildError as e:
            click.echo(f"  ✗ {e}", err=True)
            return BootstrapResult(success=False, error=str(e))

    # ── Step 5: Generate config ──
    blog.step("Step 4: Generate Configuration")
    click.echo("\n📋 Step 4: Generate Configuration\n")

    click.echo(f"  Images: {images.ploston_image}, {images.native_tools_image}")

    compose_files: list = []  # Track compose files for StackManager

    if target == "docker":
        config = ComposeConfig(
            port=port,
            with_observability=with_observability,
            ploston_image_full=images.ploston_image,
            native_tools_image_full=images.native_tools_image,
            network_name=network_name,
            network_external=network_external,
        )
        generator = ComposeGenerator()
        compose_file = generator.generate(config)
        compose_files.append(compose_file)
        click.echo(f"  ✓ Generated: {compose_file}")

        # Setup volumes
        volume_manager = VolumeManager()
        volume_manager.setup_directories()
        volume_manager.generate_seed_config()
        click.echo("  ✓ Created data directories")

        if with_observability:
            asset_manager = AssetManager()
            obs_compose = asset_manager.deploy_observability_docker(overwrite=True)
            compose_files.append(obs_compose)
            click.echo("  ✓ Deployed observability assets")

            # Inject OTEL env vars into ~/.ploston/.env so the local runner
            # (which loads this file via _load_ploston_env) forwards logs and
            # traces to the collector running on localhost (DEC-149).
            from ..init.env_manager import merge_env_file

            merge_env_file(
                {
                    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4327",
                    "OTEL_EXPORTER_OTLP_INSECURE": "true",
                    "PLOSTON_LOGS_ENABLED": "true",
                    "PLOSTON_TRACES_ENABLED": "true",
                },
                section="Observability",
            )
            click.echo("  ✓ OTEL env vars written to ~/.ploston/.env")
    else:
        # Build ingress config from --domain flag
        ingress_hosts = []
        if domain:
            ingress_hosts = [K8sIngressHost(host=f"{namespace}.{domain}")]

        k8s_config = K8sConfig(
            namespace=namespace,
            port=port,
            ploston_image_full=images.ploston_image,
            native_tools_image_full=images.native_tools_image,
            native_tools_enabled=with_native_tools,
            ingress_enabled=bool(domain),
            ingress_hosts=ingress_hosts,
        )
        k8s_generator = K8sManifestGenerator()
        manifest_dir = k8s_generator.generate(k8s_config)
        click.echo(f"  ✓ Generated manifests: {manifest_dir}")

        if with_observability:
            asset_manager = AssetManager()
            obs_k8s_dir = asset_manager.deploy_observability_k8s(overwrite=True)
            click.echo(f"  ✓ Deployed K8s observability manifests: {obs_k8s_dir}")

    # Persist the compose file list so that every StackManager() instance
    # (status, down, restart, logs) uses the same set of files.
    if target == "docker" and compose_files:
        save_stack_config(compose_files)

    # ── Step 6: Deploy ──
    blog.step("Step 5: Deploy Stack")
    click.echo("\n📋 Step 5: Deploy Stack\n")

    if target == "docker":
        stack_manager = StackManager(compose_files=compose_files if compose_files else None)
        if images.should_pull:
            click.echo("  Pulling images...")
        else:
            click.echo("  Using local images...")
        click.echo(f"  Compose files: {[str(f) for f in stack_manager.compose_files]}")
        click.echo(f"  Pull: {images.should_pull}")
        success, msg = stack_manager.up(pull=images.should_pull)
        if not success:
            blog.finish(success=False, message=msg)
            click.echo(f"  ✗ {msg}", err=True)
            # Friendly hint when pulling release images fails (no public release yet)
            if images.should_pull and not images.build_from_source:
                _msg_lower = msg.lower() if msg else ""
                if any(
                    hint in _msg_lower
                    for hint in ("pull", "manifest unknown", "not found", "denied")
                ):
                    click.echo("", err=True)
                    click.echo(
                        "  💡 Image pull failed. If no public release exists yet, try:",
                        err=True,
                    )
                    click.echo(
                        "       ploston bootstrap --edge          (latest tested dev image)",
                        err=True,
                    )
                    click.echo(
                        "       ploston bootstrap --build-from-source  (build locally)",
                        err=True,
                    )
            click.echo(f"  📝 Full debug log: {log_path}", err=True)
            return BootstrapResult(success=False, error=msg)
        click.echo("  ✓ Stack started")
    else:
        deployer = KubectlDeployer(kubeconfig)
        success, msg = deployer.apply(manifest_dir)
        if not success:
            click.echo(f"  ✗ {msg}", err=True)
            return BootstrapResult(success=False, error=msg)
        click.echo("  ✓ Manifests applied")

    # ── Step 7: Wait for health ──
    blog.step("Step 6: Wait for CP Health")
    click.echo("\n📋 Step 6: Wait for CP Health\n")

    cp_url = f"http://localhost:{port}"

    def on_attempt(attempt: int, max_attempts: int, error: str | None):
        click.echo(f"  Attempt {attempt}/{max_attempts}: {error or 'checking...'}", nl=False)
        click.echo("\r", nl=False)

    poller = HealthPoller(max_attempts=30, interval_seconds=2.0)
    health = await poller.wait_for_healthy(cp_url, on_attempt)

    if health.healthy:
        click.echo(
            f"  ✓ CP healthy (v{health.version or 'unknown'}) in {health.elapsed_seconds:.1f}s"
        )
    else:
        blog.finish(success=False, message=health.error or "health check failed")
        click.echo(f"  ✗ {health.error}", err=True)
        click.echo(f"  📝 Full debug log: {log_path}", err=True)
        return BootstrapResult(success=False, error=health.error)

    # ── Step 8: Auto-chain to import ──
    if not skip_import:
        click.echo("\n📋 Step 7: Detect & Import MCP Configs\n")
        chain_detector = AutoChainDetector()
        chain_result = chain_detector.detect()

        if chain_result.configs_found:
            click.echo(f"  Found {chain_result.total_servers} MCP server(s):")
            for name in chain_result.server_names or []:
                click.echo(f"    - {name}")

            # ── Server selection ──
            selector = ServerSelector()
            server_list = list(chain_result.servers.values())

            if non_interactive:
                selected_names = selector.select_all(server_list)
                click.echo(
                    f"\n  📦 Importing all {len(selected_names)} servers (non-interactive mode).\n"
                )
            else:
                click.echo()
                selected_names = await selector.prompt_selection(server_list)
                click.echo(f"\n  📦 {len(selected_names)} servers selected for import\n")

            if selected_names:
                # ── Import selected servers to CP ──
                from ..commands.init import _complete_import_flow

                # Determine inject: confirmation prompt (default=Yes) in interactive,
                # always inject in non-interactive.
                do_inject = True
                if not non_interactive:
                    click.echo("  Selected servers will be injected into your Claude/Cursor config")
                    click.echo(
                        "  so MCP servers route through Ploston (a backup is created first)."
                    )
                    do_inject = click.confirm("  Proceed with injection?", default=True)

                await _complete_import_flow(
                    cp_url=cp_url,
                    detected_configs=chain_result.detected_configs,
                    servers=chain_result.servers,
                    selected_names=selected_names,
                    runner_name=None,
                    inject=do_inject,
                )

                # ── Always start local runner ──
                runner = RunnerAutoStart(cp_url)
                success, msg = runner.start_runner(daemon=True)
                if success:
                    click.echo("  ✓ Runner started")
                else:
                    click.echo(f"  ⚠ {msg}")
            else:
                click.echo("  No servers selected — skipping import.")
        else:
            click.echo("  No Claude/Cursor configs found")

    # ── Done ──
    blog.finish(success=True, message=f"CP healthy at {cp_url}")
    click.echo("\n" + "=" * 50)
    click.echo("✓ Bootstrap complete!")
    click.echo(f"\n  CP URL: {cp_url}")
    click.echo(f"  Debug log: {log_path}")
    click.echo("  Status: ploston bootstrap status")
    click.echo("  Logs:   ploston bootstrap logs -f")
    click.echo("  Stop:   ploston bootstrap down")
    click.echo("=" * 50 + "\n")

    return BootstrapResult(success=True, port=port, cp_url=cp_url)
