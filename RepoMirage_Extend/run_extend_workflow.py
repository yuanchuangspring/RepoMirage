#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


DEFAULT_STEPS = ["summary", "proxy", "runtime", "constant"]


def run_command(command: list[str]) -> None:
    print("\n[run] " + " ".join(command), flush=True)
    subprocess.run(command, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the RepoMirage Extend workflow: metadata summary/task assignment, "
            "then optional task-image generation."
        )
    )
    parser.add_argument("--metadata-dir", default="repomirage_metadata")
    parser.add_argument("--output-dir", default="repomirage_metadata_stats")
    parser.add_argument("--proxy-top-k", type=int, default=144)
    parser.add_argument("--constant-top-k", type=int, default=144)
    parser.add_argument("--instance-ids-file")
    parser.add_argument(
        "--steps",
        nargs="+",
        choices=DEFAULT_STEPS,
        default=DEFAULT_STEPS,
        help="Workflow steps to run. Use only 'summary' to produce task lists without Docker image generation.",
    )
    parser.add_argument("--source-tag", default="repomirage")
    parser.add_argument("--proxy-target-tag", default="repomirage_proxy_chain")
    parser.add_argument("--runtime-target-tag", default="repomirage_runtime_target")
    parser.add_argument("--constant-target-tag", default="repomirage_missing_constant")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--placeholder", default="YOUR CODE HERE")
    parser.add_argument("--constant-sample-size", type=int, default=5)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--stop-on-error", action="store_true")
    parser.add_argument("--git-user-name", default="RepoMirage")
    parser.add_argument("--git-user-email", default="repomirage@example.invalid")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    here = Path(__file__).resolve().parent
    output_dir = Path(args.output_dir)

    if "summary" in args.steps:
        command = [
            sys.executable,
            str(here / "summary.py"),
            "--metadata-dir",
            args.metadata_dir,
            "--output-dir",
            str(output_dir),
            "--proxy-top-k",
            str(args.proxy_top_k),
            "--constant-top-k",
            str(args.constant_top_k),
        ]
        if args.instance_ids_file:
            command.extend(["--instance-ids-file", args.instance_ids_file])
        run_command(command)

    common_generation_args = [
        "--metadata-dir",
        args.metadata_dir,
        "--source-tag",
        args.source_tag,
        "--seed",
        str(args.seed),
        "--git-user-name",
        args.git_user_name,
        "--git-user-email",
        args.git_user_email,
    ]
    if args.overwrite:
        common_generation_args.append("--overwrite")

    if "proxy" in args.steps:
        run_command(
            [
                sys.executable,
                str(here / "ProxyChain.py"),
                "--proxy-top-json",
                str(output_dir / f"proxy_top_{args.proxy_top_k}.json"),
                "--target-tag",
                args.proxy_target_tag,
                "--summary-path",
                str(output_dir / "proxy_chain_generation_summary.json"),
                "--commit-message",
                "Initialize proxy-chain task image",
                *common_generation_args,
            ]
        )

    if "runtime" in args.steps:
        command = [
            sys.executable,
            str(here / "RuntimeTarget.py"),
            "--instances-json",
            str(output_dir / "remainder.json"),
            "--target-tag",
            args.runtime_target_tag,
            "--summary-path",
            str(output_dir / "runtime_target_generation_summary.json"),
            "--placeholder",
            args.placeholder,
            "--commit-message",
            "Initialize runtime-target task image",
            *common_generation_args,
        ]
        if args.stop_on_error:
            command.append("--stop-on-error")
        run_command(command)

    if "constant" in args.steps:
        run_command(
            [
                sys.executable,
                str(here / "MissingConstant.py"),
                "--instances-json",
                str(output_dir / f"constant_top_{args.constant_top_k}.json"),
                "--target-tag",
                args.constant_target_tag,
                "--summary-path",
                str(output_dir / "missing_constant_generation_summary.json"),
                "--placeholder",
                args.placeholder,
                "--sample-size",
                str(args.constant_sample_size),
                "--commit-message",
                "Initialize missing-constant task image",
                *common_generation_args,
            ]
        )

    print("\n[done] RepoMirage Extend workflow completed.", flush=True)


if __name__ == "__main__":
    main()
