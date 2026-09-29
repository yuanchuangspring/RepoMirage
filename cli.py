#!/usr/bin/env python3
"""RepoMirage unified command-line entry point.

Run from the repository root:

    python cli.py perturb [OPTIONS]      build perturbed images (Part 1)
    python cli.py extend  [STEPS]        assign tasks / build task images (Part 2)
    python cli.py export  [TASKS]        export HF-style task datasets (optional)
    python cli.py validate TASK ARGS...  validate agent repair patches

All intermediate artifacts default into `repomirage_output/` under the
repository root (override with the REPOMIRAGE_OUT environment variable).
Pass `--help` after a subcommand to see its options.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PERTURB_SCRIPT = ROOT / "RepoMirage_Perturb" / "repomirage.py"
WORKFLOW_SCRIPT = ROOT / "RepoMirage_Extend" / "run_extend_workflow.py"
EXTRACT_SCRIPT = ROOT / "RepoMirage_Extend" / "extract_dataset" / "run_extract_datasets.py"

VALIDATOR_SCRIPTS = {
    "proxy": ROOT / "RepoMirage_Extend" / "validate_ProxyChain.py",
    "runtime": ROOT / "RepoMirage_Extend" / "validate_RuntimeTarget.py",
    "constant": ROOT / "RepoMirage_Extend" / "validate_MissingConstant.py",
}

EXTEND_STEPS = ("summary", "proxy", "runtime", "constant")
EXPORT_TASKS = ("multi_file", "proxy_chain", "runtime_target", "missing_constant")

USAGE = """RepoMirage: benchmark construction for repository-context reasoning.

Usage:
  python cli.py perturb [OPTIONS]
      Build RepoMirage-perturbed SWE-bench Docker images and export metadata.
      (RepoMirage-Perturb)

  python cli.py extend [STEPS...]
      Assign instances to task families and build task-specific Docker images.
      Steps (default: summary proxy runtime constant):
        summary   write task assignment lists only (no Docker)
        proxy     build Proxy Chain Completion images
        runtime   build Runtime Target Identification images
        constant  build Missing Constant Recovery images
      Example: python cli.py extend summary

  python cli.py export [TASKS...]
      Export task lists into local Hugging Face-style datasets.
      Tasks (default: all four): multi_file, proxy_chain, runtime_target,
      missing_constant.

  python cli.py validate TASK SOLUTIONS.json FEEDBACK.json [OPTIONS]
      Validate agent repair patches. TASK is one of: proxy, runtime, constant.

All intermediate artifacts default into ./repomirage_output/ next to this
file. Set REPOMIRAGE_OUT=/some/where to relocate the whole workspace.
"""


def _run(script: Path, args: list[str]) -> int:
    return subprocess.call([sys.executable, str(script), *args])


def _translate_positional(argv: list[str], choices: tuple[str, ...]) -> list[str]:
    """Allow `cli.py extend summary` as shorthand for `--steps summary`."""
    if "--steps" in argv:
        return argv
    picked = []
    for token in argv:
        if token in choices and token not in picked:
            picked.append(token)
    if not picked:
        return argv
    rest = [token for token in argv if token not in choices]
    return ["--steps", *picked, *rest]


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(USAGE, end="")
        return 0

    command, args = sys.argv[1], sys.argv[2:]

    if command == "perturb":
        return _run(PERTURB_SCRIPT, args)

    if command == "extend":
        return _run(WORKFLOW_SCRIPT, _translate_positional(args, EXTEND_STEPS))

    if command == "export":
        return _run(EXTRACT_SCRIPT, _translate_positional(args, EXPORT_TASKS))

    if command == "validate":
        if not args or args[0] in ("-h", "--help"):
            print("Usage: python cli.py validate TASK SOLUTIONS.json FEEDBACK.json [OPTIONS]\n")
            print("TASK is one of: proxy, runtime, constant.")
            return 0
        task, rest = args[0], args[1:]
        script = VALIDATOR_SCRIPTS.get(task)
        if script is None:
            print(f"Unknown validation task '{task}'. Choose from: proxy, runtime, constant.")
            return 2
        return _run(script, rest)

    print(f"Unknown command '{command}'.")
    print(USAGE, end="")
    return 2


if __name__ == "__main__":
    sys.exit(main())
