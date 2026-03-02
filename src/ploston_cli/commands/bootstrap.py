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
    AutoChainDetector,
    BootstrapAction,
    BootstrapStateManager,
    ComposeConfig,
    ComposeGenerator,
    DockerDetector,
    HealthPoller,
    ImportHandoff,
    K8sConfig,
    K8sManifestGenerator,
    KubectlDeployer,
    KubectlDetector,
    NetworkManager,
    PortScanner,
    RunnerAutoStart,
    StackManager,
    StackState,
    VolumeManager,
)

DEFAULT_NETWORK_NAME = "ploston-network"


@dataclass
class BootstrapResult:
    """Result of bootstrap execution."""

    success: bool
    port: int = 8082
    cp_url: str = "http://localhost:8082"
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
@click.option("--tag", default="edge", help="Docker image tag")
@click.option("--port", default=8082, type=int, help="CP port")
@click.option(
    "--with-observability",
    is_flag=True,
    help="Include Prometheus + Grafana + Loki",
)
@click.option("--no-import", is_flag=True, help="Skip auto-detection and import chaining")
@click.option("--no-pull", is_flag=True, help="Skip pulling images (use local images)")
@click.option("--non-interactive", "-y", is_flag=True, help="Accept all defaults")
@click.option("--kubeconfig", default=None, help="Kubeconfig path (K8s only)")
@click.option("--namespace", default="ploston", help="K8s namespace")
@click.option("--network", default=DEFAULT_NETWORK_NAME, help="Docker network name")
@click.pass_context
def bootstrap(
    ctx,
    target,
    tag,
    port,
    with_observability,
    no_import,
    no_pull,
    non_interactive,
    kubeconfig,
    namespace,
    network,
):
    """Deploy the Ploston Control Plane.

    This command deploys the Ploston Control Plane stack to Docker Compose
    (default) or Kubernetes. It handles prerequisites, generates configuration,
    starts services, and waits for the CP to become healthy.

    Examples:

        # Deploy to Docker Compose (default)
        ploston bootstrap

        # Deploy with observability stack
        ploston bootstrap --with-observability

        # Deploy to Kubernetes
        ploston bootstrap --target k8s --namespace ploston

        # Use specific image tag
        ploston bootstrap --tag v1.0.0

        # Use a different network name
        ploston bootstrap --network my-custom-network
    """
    if ctx.invoked_subcommand is not None:
        return  # Subcommand handles it

    asyncio.run(
        _run_bootstrap(
            target=target,
            tag=tag,
            port=port,
            with_observability=with_observability,
            skip_import=no_import,
            skip_pull=no_pull,
            non_interactive=non_interactive,
            kubeconfig=kubeconfig,
            namespace=namespace,
            network_name=network,
        )
    )


@bootstrap.command()
def status():
    """Show current stack status."""
    manager = StackManager()
    stack_status = manager.status()

    if stack_status.state == StackState.NOT_FOUND:
        click.echo("No Ploston stack found. Run: ploston bootstrap")
        return

    click.echo(f"Stack state: {stack_status.state.value}")
    if stack_status.running_services:
        click.echo("Running services:")
        for svc in stack_status.running_services:
            click.echo(f"  ✓ {svc}")
    if stack_status.stopped_services:
        click.echo("Stopped services:")
        for svc in stack_status.stopped_services:
            click.echo(f"  ✗ {svc}")


@bootstrap.command()
@click.option("--volumes", is_flag=True, help="Also remove volumes (data loss!)")
@click.option(
    "--target",
    type=click.Choice(["docker", "k8s"]),
    default="docker",
)
@click.option("--namespace", default="ploston")
@click.option("--kubeconfig", default=None)
def down(volumes, target, namespace, kubeconfig):
    """Stop and remove the Ploston stack."""
    if target == "docker":
        manager = StackManager()
        if volumes:
            if not click.confirm("This will delete all Ploston data. Continue?"):
                return
        success, msg = manager.down(remove_volumes=volumes)
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
    manager.logs(follow=follow, service=service, tail=tail)


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


async def _run_bootstrap(
    target: str,
    tag: str,
    port: int,
    with_observability: bool,
    skip_import: bool,
    skip_pull: bool,
    non_interactive: bool,
    kubeconfig: str | None = None,
    namespace: str = "ploston",
    network_name: str = DEFAULT_NETWORK_NAME,
) -> BootstrapResult:
    """Execute the full bootstrap flow."""
    click.echo("\n🚀 Ploston Bootstrap\n")

    # ── Step 1: Check existing state ──
    state_manager = BootstrapStateManager()
    state = state_manager.detect_state()

    if state.stack_running:
        click.echo("📋 Existing Stack Detected\n")
        click.echo(f"  Running services: {', '.join(state.running_services or [])}")

        if non_interactive:
            click.echo("\n  Using existing stack (non-interactive mode)")
            return BootstrapResult(success=True, port=port)

        click.echo("\nOptions:")
        click.echo("  [1] Keep running (nothing to do)")
        click.echo("  [2] Restart stack")
        click.echo("  [3] Recreate stack (pull latest images)")
        click.echo("  [4] Tear down")

        choice = click.prompt("Select option", type=click.Choice(["1", "2", "3", "4"]), default="1")

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
            success, msg = state_manager.execute_action(action)
            click.echo(f"\n{'✓' if success else '✗'} {msg}")
            return BootstrapResult(success=success, port=port)
        else:
            success, msg = state_manager.execute_action(action)
            if not success:
                click.echo(f"\n✗ {msg}", err=True)
                return BootstrapResult(success=False, error=msg)
            click.echo(f"\n✓ {msg}")
            return BootstrapResult(success=True, port=port)

    # ── Step 2: Prerequisites ──
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
        if kubectl.cluster_available:
            click.echo(f"  ✓ Cluster: {kubectl.cluster_name}")
        else:
            click.echo("  ✗ No cluster available", err=True)
            return BootstrapResult(success=False, error="No K8s cluster available")

    # ── Step 3: Port check ──
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

    # ── Step 5: Generate config ──
    click.echo("\n📋 Step 4: Generate Configuration\n")

    if target == "docker":
        config = ComposeConfig(
            tag=tag,
            port=port,
            with_observability=with_observability,
            network_name=network_name,
            network_external=network_external,
        )
        generator = ComposeGenerator()
        compose_file = generator.generate(config)
        click.echo(f"  ✓ Generated: {compose_file}")

        # Setup volumes
        volume_manager = VolumeManager()
        volume_manager.setup_directories()
        volume_manager.generate_seed_config()
        click.echo("  ✓ Created data directories")

        if with_observability:
            volume_manager.setup_observability_directories()
            volume_manager.generate_prometheus_config()
            volume_manager.generate_loki_config()
            click.echo("  ✓ Created observability configs")
    else:
        k8s_config = K8sConfig(
            namespace=namespace,
            tag=tag,
            port=port,
        )
        k8s_generator = K8sManifestGenerator()
        manifest_dir = k8s_generator.generate(k8s_config)
        click.echo(f"  ✓ Generated manifests: {manifest_dir}")

    # ── Step 6: Deploy ──
    click.echo("\n📋 Step 5: Deploy Stack\n")

    if target == "docker":
        stack_manager = StackManager()
        if not skip_pull:
            click.echo("  Pulling images...")
        else:
            click.echo("  Using local images (--no-pull)...")
        success, msg = stack_manager.up(pull=not skip_pull)
        if not success:
            click.echo(f"  ✗ {msg}", err=True)
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
        click.echo(f"  ✗ {health.error}", err=True)
        return BootstrapResult(success=False, error=health.error)

    # ── Step 8: Auto-chain to import ──
    if not skip_import:
        click.echo("\n📋 Step 7: Detect MCP Configs\n")
        chain_detector = AutoChainDetector()
        chain_result = chain_detector.detect()

        if chain_result.configs_found:
            click.echo(f"  Found {chain_result.total_servers} MCP server(s):")
            for name in chain_result.server_names or []:
                click.echo(f"    - {name}")

            if non_interactive or click.confirm("\n  Import these configs to CP?", default=True):
                handoff = ImportHandoff(cp_url)
                success, msg = handoff.run_import(interactive=not non_interactive)
                if success:
                    click.echo("  ✓ Configs imported")

                    # Offer to start runner
                    if non_interactive or click.confirm("\n  Start local runner?", default=True):
                        runner = RunnerAutoStart(cp_url)
                        success, msg = runner.start_runner(daemon=True)
                        if success:
                            click.echo("  ✓ Runner started")
                        else:
                            click.echo(f"  ⚠ {msg}")
                else:
                    click.echo(f"  ⚠ Import failed: {msg}")
        else:
            click.echo("  No Claude/Cursor configs found")

    # ── Done ──
    click.echo("\n" + "=" * 50)
    click.echo("✓ Bootstrap complete!")
    click.echo(f"\n  CP URL: {cp_url}")
    click.echo("  Status: ploston bootstrap status")
    click.echo("  Logs:   ploston bootstrap logs -f")
    click.echo("  Stop:   ploston bootstrap down")
    click.echo("=" * 50 + "\n")

    return BootstrapResult(success=True, port=port, cp_url=cp_url)
