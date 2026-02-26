"""Interactive setup tool for Azure DevOps pipelines.

Usage:  python3 setup.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Ensure packages are importable when run as standalone script
sys.path.insert(0, str(Path(__file__).resolve().parent))

from rich.panel import Panel
from rich.prompt import Confirm, Prompt, IntPrompt
from rich.table import Table

from shared import settings
from shared.ado import logger
from shared.ado.client import AdoClient
from shared.ado.environment import EnvironmentService
from shared.ado.approval import ApprovalService
from shared.ado.pipeline import PipelineService
from shared.console import console
from promote.services.git import GitService

# Promotion pipeline definitions: (name_template, yaml_template, source_env, target_env)
PROMOTE_PIPELINE_DEFS = [
    ("DEV-to-QA", "pipelines/dev-to-qa.yml", "dev", "qa"),
    ("QA-to-STG", "pipelines/qa-to-stg.yml", "qa", "stg"),
    ("STG-to-PRD", "pipelines/stg-to-prd.yml", "stg", "prd"),
]


# ── Shared helpers ──


def prompt_pat() -> str:
    """Prompt for PAT and return it, or exit on empty."""
    pat = Prompt.ask("[bold]Personal Access Token (PAT)[/bold]", password=True)
    if not pat:
        logger.error("PAT cannot be empty.")
        sys.exit(1)
    return pat


def validate_client(client: AdoClient) -> None:
    """Validate PAT or exit."""
    with console.status("[bold blue]Validating PAT...[/bold blue]"):
        if not client.validate_pat():
            logger.error("PAT validation failed. Check your token and permissions.")
            sys.exit(1)
    logger.success("PAT is valid.")


def parse_remote(url: str) -> tuple[str, str, str]:
    """Extract (org, project, repo_name) from an Azure DevOps remote URL."""
    patterns = [
        r"git@ssh\.dev\.azure\.com:v3/([^/]+)/([^/]+)/(.+?)(?:\.git)?$",
        r"https://dev\.azure\.com/([^/]+)/([^/]+)/_git/(.+?)(?:\.git)?$",
        r"https://[^@]+@dev\.azure\.com/([^/]+)/([^/]+)/_git/(.+?)(?:\.git)?$",
    ]
    for pattern in patterns:
        match = re.match(pattern, url)
        if match:
            return match.group(1), match.group(2), match.group(3)

    print(
        f"ERROR: Unrecognized Azure DevOps remote URL format: {url}\n"
        "Supported formats:\n"
        "  SSH:   git@ssh.dev.azure.com:v3/{org}/{project}/{repo}\n"
        "  HTTPS: https://dev.azure.com/{org}/{project}/_git/{repo}",
        file=sys.stderr,
    )
    sys.exit(1)


# ── 1. Show users ──


def show_users() -> int:
    """List all users in the ADO organization with their GUIDs."""
    org = settings.org()
    project = settings.project()

    console.print(Panel(
        f"[bold]Organization:[/bold] {org}\n[bold]Project:[/bold]      {project}",
        title="[bold cyan]Azure DevOps Users[/bold cyan]",
        border_style="cyan",
    ))

    pat = prompt_pat()
    client = AdoClient(org, project, pat)
    validate_client(client)

    with console.status("[bold blue]Fetching users...[/bold blue]"):
        data = client.get_vsaex("_apis/userentitlements?$top=500")
    entries = data.get("items", [])

    if not entries:
        logger.warning("No users found.")
        return 0

    table = Table(
        title=f"Users in [bold]{org}[/bold] ({len(entries)} total)",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("#", justify="right", style="dim", width=4)
    table.add_column("Name", style="bold")
    table.add_column("ID", style="cyan")
    table.add_column("Email", style="dim")

    for i, entry in enumerate(
        sorted(entries, key=lambda e: e.get("user", {}).get("displayName", "")),
        1,
    ):
        user = entry.get("user", {})
        table.add_row(
            str(i),
            user.get("displayName", "Unknown"),
            entry.get("id", ""),
            user.get("mailAddress", ""),
        )

    console.print()
    console.print(table)

    console.print()
    console.rule("[bold green]Copy to settings.yaml[/bold green]")
    console.print()
    lines = ["[bold]approvers:[/bold]"]
    for entry in sorted(
        entries,
        key=lambda e: e.get("user", {}).get("displayName", ""),
    ):
        user = entry.get("user", {})
        name = user.get("displayName", "Unknown")
        user_id = entry.get("id", "")
        lines.append(f'  - name: "{name}"')
        lines.append(f'    id: "{user_id}"')
    console.print("\n".join(lines))
    console.print()

    return 0


# ── 2. Install Main Pipeline ──

MAIN_PIPELINE_NAME = "Main"
MAIN_PIPELINE_YAML = "pipelines/main.yml"
MAIN_DEFAULT_BRANCH = "refs/heads/main"


def install_main_pipeline() -> int:
    """Set up the main (CI) pipeline definition in Azure DevOps."""
    # 1. Prompt for repo dir
    repo_dir = Prompt.ask("[bold]Repository directory[/bold]")
    if not repo_dir or not Path(repo_dir).is_dir():
        logger.error(f"Directory does not exist: {repo_dir}")
        return 1

    git = GitService(repo_dir)

    # 2. Load settings
    org = settings.org()
    project = settings.project()

    # 3. Detect repo name from git remote
    remote_url = git.remote_url()
    _, _, repo_name = parse_remote(remote_url)
    folder = f"\\{repo_name}"

    # 4. Header
    console.print(Panel(
        f"[bold]Org:[/bold]     {org}\n"
        f"[bold]Project:[/bold] {project}\n"
        f"[bold]Repo:[/bold]    {repo_name}",
        title="[bold cyan]Azure DevOps Main Pipeline Setup[/bold cyan]",
        border_style="cyan",
    ))

    # 5. Prompt for PAT
    pat = prompt_pat()
    client = AdoClient(org, project, pat)
    validate_client(client)

    # 6. Show plan
    console.print()
    plan_table = Table(show_header=False, box=None, padding=(0, 2))
    plan_table.add_column("Key", style="bold")
    plan_table.add_column("Value")
    plan_table.add_row("Pipeline", MAIN_PIPELINE_NAME)
    plan_table.add_row("YAML", MAIN_PIPELINE_YAML)
    plan_table.add_row("Branch", MAIN_DEFAULT_BRANCH)
    plan_table.add_row("Folder", folder)
    console.print(Panel(plan_table, title="[bold]Setup Plan[/bold]", border_style="blue"))

    # 7. Get repo ID
    with console.status("[bold blue]Fetching repository ID...[/bold blue]"):
        repo_data = client.get(f"_apis/git/repositories/{repo_name}")
    repo_id = repo_data["id"]
    logger.success(f"Repository ID: {repo_id}")

    # 8. Create or update pipeline
    pipeline_svc = PipelineService(client)
    existing_id = pipeline_svc.find_by_name_and_folder(MAIN_PIPELINE_NAME, folder)

    if existing_id is not None:
        logger.warning(f"Pipeline '{MAIN_PIPELINE_NAME}' already exists (ID: {existing_id})")
        overwrite = Confirm.ask("[bold]Update existing pipeline?[/bold]", default=False)
        if overwrite:
            with console.status("[bold blue]Updating pipeline...[/bold blue]"):
                pipeline_svc.update(
                    existing_id, MAIN_PIPELINE_YAML, repo_id, repo_name, MAIN_DEFAULT_BRANCH
                )
            pipeline_id = existing_id
            logger.success(f"Pipeline '{MAIN_PIPELINE_NAME}' updated (ID: {pipeline_id})")
        else:
            pipeline_id = existing_id
            logger.info("Skipping pipeline update.")
    else:
        with console.status(f"[bold blue]Creating pipeline '{MAIN_PIPELINE_NAME}'...[/bold blue]"):
            pipeline_id, _ = pipeline_svc.get_or_create(
                MAIN_PIPELINE_NAME, folder, MAIN_PIPELINE_YAML,
                repo_id, repo_name, MAIN_DEFAULT_BRANCH,
            )
        logger.success(f"Pipeline '{MAIN_PIPELINE_NAME}' created (ID: {pipeline_id})")

    # 9. Summary
    encoded_folder = folder.replace("\\", "%5C")
    ado_url = f"{client.base_url}/_build?definitionScope={encoded_folder}"

    summary_table = Table(show_header=False, box=None, padding=(0, 2))
    summary_table.add_column("Key", style="bold")
    summary_table.add_column("Value")
    summary_table.add_row("Pipeline", f"{MAIN_PIPELINE_NAME} (folder: {folder})")
    summary_table.add_row("YAML", MAIN_PIPELINE_YAML)
    summary_table.add_row("Trigger", "all branches (push + PR)")
    summary_table.add_row("ADO URL", f"[link={ado_url}]{ado_url}[/link]")

    console.print()
    console.print(Panel(
        summary_table,
        title="[bold green]Setup Complete[/bold green]",
        border_style="green",
    ))
    console.print()

    return 0


# ── 3. Install Promote Pipeline ──


def install_promote_pipeline() -> int:
    """Interactively set up promotion pipelines, environments, and approval checks."""
    # 1. Prompt for repo dir
    repo_dir = Prompt.ask("[bold]Repository directory[/bold]")
    if not repo_dir or not Path(repo_dir).is_dir():
        logger.error(f"Directory does not exist: {repo_dir}")
        return 1

    git = GitService(repo_dir)

    # 2. Load settings
    org = settings.org()
    project = settings.project()
    approvers = settings.approvers()

    # 3. Detect repo name from git remote
    remote_url = git.remote_url()
    _, _, repo_name = parse_remote(remote_url)
    folder = f"\\{repo_name}"

    # 4. Header
    console.print(Panel(
        f"[bold]Org:[/bold]     {org}\n"
        f"[bold]Project:[/bold] {project}\n"
        f"[bold]Repo:[/bold]    {repo_name}",
        title="[bold cyan]Azure DevOps Promotion Pipeline Setup[/bold cyan]",
        border_style="cyan",
    ))

    # 5. Prompt for PAT
    pat = prompt_pat()
    client = AdoClient(org, project, pat)
    validate_client(client)

    # 6. Prompt for stream number
    stream = Prompt.ask("[bold]Stream number[/bold]", default="01")
    if not re.fullmatch(r"\d{2}", stream):
        logger.error("Stream number must be exactly 2 digits (e.g. 01, 02, 03).")
        return 1

    # 7. Pipeline selection
    console.print()
    menu_table = Table(
        title="Select promotion pipeline",
        show_header=True,
        header_style="bold magenta",
    )
    menu_table.add_column("#", justify="right", style="bold", width=3)
    menu_table.add_column("Pipeline", style="bold cyan")
    menu_table.add_column("Flow", style="green")

    for i, (name, _, src_env, tgt_env) in enumerate(PROMOTE_PIPELINE_DEFS, 1):
        menu_table.add_row(
            str(i),
            name,
            f"{src_env}-{stream} \u2192 {tgt_env}-{stream}",
        )
    console.print(menu_table)
    console.print()

    choice = IntPrompt.ask(
        "[bold]Choice[/bold]",
        choices=[str(i) for i in range(1, len(PROMOTE_PIPELINE_DEFS) + 1)],
    )
    idx = choice - 1

    pipeline_name, yaml_path, source_env, target_env = PROMOTE_PIPELINE_DEFS[idx]
    source_branch = f"{source_env}-{stream}"
    target_branch = f"{target_env}-{stream}"
    default_branch = f"refs/heads/{source_branch}"

    if stream != "01":
        pipeline_name = f"{pipeline_name}-{stream}"

    # 8. Show plan
    console.print()
    plan_table = Table(show_header=False, box=None, padding=(0, 2))
    plan_table.add_column("Key", style="bold")
    plan_table.add_column("Value")
    plan_table.add_row("Pipeline", pipeline_name)
    plan_table.add_row("YAML", yaml_path)
    plan_table.add_row("Branch", default_branch)
    plan_table.add_row("Flow", f"{source_branch} \u2192 {target_branch}")
    plan_table.add_row("Environment", target_env)
    console.print(Panel(plan_table, title="[bold]Setup Plan[/bold]", border_style="blue"))

    # 9. Get repo ID
    with console.status("[bold blue]Fetching repository ID...[/bold blue]"):
        repo_data = client.get(f"_apis/git/repositories/{repo_name}")
    repo_id = repo_data["id"]
    logger.success(f"Repository ID: {repo_id}")

    # 10. Create/get environment
    with console.status(f"[bold blue]Creating environment '{target_env}'...[/bold blue]"):
        env_svc = EnvironmentService(client)
        env_id, env_created = env_svc.get_or_create(target_env)
    if env_created:
        logger.success(f"Environment '{target_env}' created (ID: {env_id})")
    else:
        logger.success(f"Environment '{target_env}' already exists (ID: {env_id})")

    # 11. Add approval check
    min_required = settings.min_approvers(target_env)
    with console.status("[bold blue]Configuring approval check...[/bold blue]"):
        approval_svc = ApprovalService(client)
        check_id, check_created = approval_svc.get_or_create(
            env_id, target_env, approvers, min_required
        )
    if check_created:
        logger.success(f"Approval check created (ID: {check_id})")
    else:
        logger.warning(
            f"Approval check already exists on '{target_env}' "
            f"(check ID: {check_id}). Skipping."
        )

    # 12. Create or update pipeline
    pipeline_svc = PipelineService(client)
    existing_id = pipeline_svc.find_by_name_and_folder(pipeline_name, folder)

    if existing_id is not None:
        logger.warning(f"Pipeline '{pipeline_name}' already exists (ID: {existing_id})")
        overwrite = Confirm.ask("[bold]Update existing pipeline?[/bold]", default=False)
        if overwrite:
            with console.status("[bold blue]Updating pipeline...[/bold blue]"):
                pipeline_svc.update(
                    existing_id, yaml_path, repo_id, repo_name, default_branch
                )
            pipeline_id = existing_id
            logger.success(f"Pipeline '{pipeline_name}' updated (ID: {pipeline_id})")
        else:
            pipeline_id = existing_id
            logger.info("Skipping pipeline update.")
    else:
        with console.status(f"[bold blue]Creating pipeline '{pipeline_name}'...[/bold blue]"):
            pipeline_id, _ = pipeline_svc.get_or_create(
                pipeline_name, folder, yaml_path, repo_id, repo_name, default_branch
            )
        logger.success(f"Pipeline '{pipeline_name}' created (ID: {pipeline_id})")

    # 13. Summary
    approver_names = ", ".join(a["displayName"] for a in approvers)
    encoded_folder = folder.replace("\\", "%5C")
    ado_url = f"{client.base_url}/_build?definitionScope={encoded_folder}"

    summary_table = Table(show_header=False, box=None, padding=(0, 2))
    summary_table.add_column("Key", style="bold")
    summary_table.add_column("Value")
    summary_table.add_row("Pipeline", f"{pipeline_name} (folder: {folder})")
    summary_table.add_row("YAML", yaml_path)
    summary_table.add_row("Environment", f"{target_env} (ID: {env_id})")
    summary_table.add_row("Approvers", approver_names)
    summary_table.add_row("ADO URL", f"[link={ado_url}]{ado_url}[/link]")

    console.print()
    console.print(Panel(
        summary_table,
        title="[bold green]Setup Complete[/bold green]",
        border_style="green",
    ))
    console.print()

    return 0


# ── Main menu ──


def main() -> int:
    """Show interactive menu and dispatch to the selected action."""
    console.print()
    console.print(Panel(
        "[bold]Azure DevOps Pipeline Setup Tool[/bold]",
        border_style="cyan",
    ))

    menu_table = Table(show_header=False, box=None, padding=(0, 2))
    menu_table.add_column("#", justify="right", style="bold", width=3)
    menu_table.add_column("Action", style="cyan")
    menu_table.add_row("1", "Get / show users")
    menu_table.add_row("2", "Install Main Pipeline")
    menu_table.add_row("3", "Install Promote Pipeline")
    console.print(menu_table)
    console.print()

    choice = IntPrompt.ask("[bold]Choice[/bold]", choices=["1", "2", "3"])

    actions = {
        1: show_users,
        2: install_main_pipeline,
        3: install_promote_pipeline,
    }
    return actions[choice]()


if __name__ == "__main__":
    sys.exit(main())
