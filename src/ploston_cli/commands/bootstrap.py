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
    PortScanner,
    RunnerAutoStart,
    StackManager,
    StackState,
    VolumeManager,
)


@dataclass
class BootstrapResult:
    """Result of bootstrap execution."""

    success: bool
    port: int = 8082
    cp_url: str = "http://localhost:8082"
    error: str | None = None


@click.group(invoke_without_command=True)
@click.option(
    "--target",
    type=click.Choice(["docker", "k8s"]),
    default="docker",
    help="Deployment target",
)
@click.option("--tag", default="latest", help="Docker image tag")
@click.option("--port", default=8082, type=int, help="CP port")
@click.option(
    "--with-observability",
    is_flag=True,
    help="Include Prometheus + Grafana + Loki",
)
@click.option("--no-import", is_flag=True, help="Skip auto-detection and import chaining")
@click.option("--non-interactive", "-y", is_flag=True, help="Accept all defaults")
@click.option("--kubeconfig", default=None, help="Kubeconfig path (K8s only)")
@click.option("--namespace", default="ploston", help="K8s namespace")
@click.pass_context
def bootstrap(
    ctx,
    target,
    tag,
    port,
    with_observability,
    no_import,
    non_interactive,
    kubeconfig,
    namespace,
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
            non_interactive=non_interactive,
            kubeconfig=kubeconfig,
            namespace=namespace,
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
    non_interactive: bool,
    kubeconfig: str | None = None,
    namespace: str = "ploston",
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
    port_status = scanner.check_ports([port, 6379])

    for p, status in port_status.items():
        if status.available:
            click.echo(f"  ✓ Port {p}: available")
        else:
            click.echo(f"  ✗ Port {p}: in use by {status.process_name or 'unknown'}")
            if not non_interactive:
                alt = scanner.suggest_alternative(p)
                if alt and click.confirm(f"  Use port {alt} instead?"):
                    if p == port:
                        port = alt
                else:
                    return BootstrapResult(success=False, error=f"Port {p} in use")

    # ── Step 4: Generate config ──
    click.echo("\n📋 Step 3: Generate Configuration\n")

    if target == "docker":
        config = ComposeConfig(
            tag=tag,
            port=port,
            with_observability=with_observability,
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

    # ── Step 5: Deploy ──
    click.echo("\n📋 Step 4: Deploy Stack\n")

    if target == "docker":
        stack_manager = StackManager()
        click.echo("  Pulling images...")
        success, msg = stack_manager.up(pull=True)
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

    # ── Step 6: Wait for health ──
    click.echo("\n📋 Step 5: Wait for CP Health\n")

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

    # ── Step 7: Auto-chain to import ──
    if not skip_import:
        click.echo("\n📋 Step 6: Detect MCP Configs\n")
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
