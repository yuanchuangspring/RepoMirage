#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


TASKS = {
    "multi_file": {
        "list": "touched_files_gt1_*.json",
        "output": "repomirage_multifile",
        "image_tag_arg": "multi_file_image_tag",
    },
    "proxy_chain": {
        "list": "proxy_top_{proxy_top_k}.json",
        "output": "repomirage_proxy_chain",
        "image_tag_arg": "proxy_image_tag",
    },
    "runtime_target": {
        "list": "remainder.json",
        "output": "repomirage_runtime_target",
        "image_tag_arg": "runtime_image_tag",
    },
    "missing_constant": {
        "list": "constant_top_{constant_top_k}.json",
        "output": "repomirage_missing_constant",
        "image_tag_arg": "constant_image_tag",
    },
}


def resolve_task_list(stats_dir: Path, pattern: str) -> Path:
    if "*" not in pattern:
        path = stats_dir / pattern
        if not path.exists():
            raise FileNotFoundError(f"Task list not found: {path}")
        return path

    matches = sorted(stats_dir.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"No task list matched: {stats_dir / pattern}")
    if len(matches) > 1:
        names = ", ".join(path.name for path in matches)
        raise RuntimeError(f"Multiple task lists matched {pattern}: {names}. Pass an explicit --steps subset or clean the stats dir.")
    return matches[0]


def run_command(command: list[str]) -> None:
    print("\n[run] " + " ".join(command), flush=True)
    subprocess.run(command, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract all RepoMirage task lists into local Hugging Face datasets.")
    parser.add_argument("--input-dataset", required=True, help="Source SWE-bench dataset path or HF dataset name.")
    parser.add_argument("--stats-dir", required=True, help="Directory produced by RepoMirage_Extend/summary.py.")
    parser.add_argument("--output-root", default="repomirage_hf_datasets")
    parser.add_argument("--split", default="test")
    parser.add_argument("--proxy-top-k", type=int, default=144)
    parser.add_argument("--constant-top-k", type=int, default=144)
    parser.add_argument(
        "--steps",
        nargs="+",
        choices=sorted(TASKS),
        default=list(TASKS),
        help="Task datasets to export.",
    )
    parser.add_argument("--multi-file-image-tag", default="repomirage")
    parser.add_argument("--proxy-image-tag", default="repomirage_proxy_chain")
    parser.add_argument("--runtime-image-tag", default="repomirage_runtime_target")
    parser.add_argument("--constant-image-tag", default="repomirage_missing_constant")
    parser.add_argument("--image-prefix", default="swebench/sweb.eval.x86_64.")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    here = Path(__file__).resolve().parent
    stats_dir = Path(args.stats_dir)
    output_root = Path(args.output_root)

    for task_type in args.steps:
        spec = TASKS[task_type]
        pattern = spec["list"].format(proxy_top_k=args.proxy_top_k, constant_top_k=args.constant_top_k)
        task_list = resolve_task_list(stats_dir, pattern)
        image_tag = getattr(args, spec["image_tag_arg"])
        command = [
            sys.executable,
            str(here / "build_hf_dataset.py"),
            "--input-dataset",
            args.input_dataset,
            "--split",
            args.split,
            "--task-list-json",
            str(task_list),
            "--output-dir",
            str(output_root / spec["output"]),
            "--task-type",
            task_type,
            "--image-tag",
            image_tag,
            "--image-prefix",
            args.image_prefix,
        ]
        if args.overwrite:
            command.append("--overwrite")
        run_command(command)

    print("\n[done] Exported RepoMirage task datasets.", flush=True)


if __name__ == "__main__":
    main()
