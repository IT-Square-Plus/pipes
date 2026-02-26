"""Allow running promote as ``python3 -m promote {precheck|execute}``."""

import argparse
import sys

from promote.models.context import PromotionContext
from promote.commands.precheck import PreCheckCommand
from promote.commands.execute import ExecuteCommand


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="promote",
        description="Code promotion commands for Azure DevOps pipelines.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name, help_text in [
        ("precheck", "Gather promotion details and produce a summary"),
        ("execute", "Perform the promotion (merge, tag, push)"),
    ]:
        sub = subparsers.add_parser(name, help=help_text)
        sub.add_argument("--source-branch", required=True, help="Source branch name")
        sub.add_argument("--target-branch", required=True, help="Target branch name")
        sub.add_argument("--source-env", required=True, help="Source environment (dev/qa/stg)")
        sub.add_argument("--target-env", required=True, help="Target environment (qa/stg/prd)")
        sub.add_argument("--repo-dir", required=True, help="Path to the repository working directory")

    args = parser.parse_args(argv)

    ctx = PromotionContext(
        source_branch=args.source_branch,
        target_branch=args.target_branch,
        source_env=args.source_env,
        target_env=args.target_env,
        repo_dir=args.repo_dir,
    )

    commands = {"precheck": PreCheckCommand, "execute": ExecuteCommand}
    return commands[args.command](ctx).execute()


sys.exit(main())
