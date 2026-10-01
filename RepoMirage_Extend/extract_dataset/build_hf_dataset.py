#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

try:
    from datasets import DatasetDict, load_dataset, load_from_disk
except ModuleNotFoundError:
    DatasetDict = None
    load_dataset = None
    load_from_disk = None


IMAGE_PREFIX = "swebench/sweb.eval.x86_64."

PROXY_CHAIN_PROMPT = """In the current repository, three files have been accidentally cleared, and they now have only one line of comment:

# <YOUR CODE HERE>

Please infer what their code should be, and complete them.
Please note that you are only allowed to modify the contents of these files. You can read other files, but cannot modify them.
"""

RUNTIME_TARGET_PROMPT = """In the current repository, one file was accidentally corrupted, and one placeholder was left in it:

YOUR CODE HERE

Please infer what should be there and restore the file so that the repository behaves correctly again. You should do lots of testing to do the task better.
You are only allowed to modify this one file. You may read any other files in the repository, but you must not modify them.
"""

MISSING_CONSTANT_PROMPT = """In the current repository, there are several JSON files in some directories, in which several keys have been tampered with as "YOUR CODE HERE".
You need to infer and restore these keys based on other files in this directory.
Please note that you are only authorized to modify those target JSON files and read other code files, but are not allowed to modify other code files.
Note: If there are same keys with the same values, you do not need to figure out the exact JSON file each key belongs to, as long as it is reasonable. The important thing is to match the key and value correctly.
"""

BUILTIN_PROMPTS = {
    "multi_file": None,
    "proxy_chain": PROXY_CHAIN_PROMPT,
    "runtime_target": RUNTIME_TARGET_PROMPT,
    "missing_constant": MISSING_CONSTANT_PROMPT,
}


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_instance_ids(task_list_json: str | Path) -> list[str]:
    path = Path(task_list_json)
    payload = load_json(path)
    if not isinstance(payload, list):
        raise ValueError(f"Expected a JSON list in {path}")

    instance_ids: list[str] = []
    seen: set[str] = set()
    for item in payload:
        if isinstance(item, dict):
            instance_id = item.get("instance_id")
        elif isinstance(item, str):
            instance_id = item
        else:
            instance_id = None
        if isinstance(instance_id, str) and instance_id and instance_id not in seen:
            seen.add(instance_id)
            instance_ids.append(instance_id)
    return instance_ids


def load_source_dataset(input_dataset: str, split: str):
    if load_from_disk is None or load_dataset is None or DatasetDict is None:
        raise RuntimeError("Missing Python package 'datasets'. Install it first, for example: pip install datasets")

    try:
        dataset = load_from_disk(input_dataset)
    except Exception:
        dataset = load_dataset(input_dataset)

    if isinstance(dataset, DatasetDict):
        if split in dataset:
            return dataset[split]
        if split == "test" and "train" in dataset:
            print("[warn] Split 'test' not found; using 'train' instead.")
            return dataset["train"]
        available = ", ".join(dataset.keys())
        raise ValueError(f"Split '{split}' not found. Available splits: {available}")

    return dataset


def instance_id_to_image(instance_id: str, image_tag: str, image_prefix: str) -> str:
    docker_compatible = instance_id.replace("__", "_1776_")
    return f"{image_prefix}{docker_compatible}:{image_tag}"


def read_problem_statement(args: argparse.Namespace) -> str | None:
    if args.problem_statement_file:
        return Path(args.problem_statement_file).read_text(encoding="utf-8")
    if args.problem_statement:
        return args.problem_statement
    return BUILTIN_PROMPTS.get(args.task_type)


def dataset_info_to_dict(info: Any) -> dict[str, Any]:
    if hasattr(info, "to_dict"):
        return info.to_dict()
    if is_dataclass(info):
        return asdict(info)
    if hasattr(info, "__dict__"):
        return dict(info.__dict__)
    return {"repr": repr(info)}


def build_dataset(args: argparse.Namespace) -> None:
    instance_ids = load_instance_ids(args.task_list_json)
    if not instance_ids:
        print(f"[skip] Task list {args.task_list_json} contains no instances; nothing to export.")
        return

    id_rank = {instance_id: rank for rank, instance_id in enumerate(instance_ids)}
    id_set = set(instance_ids)
    source_dataset = load_source_dataset(args.input_dataset, args.split)
    print(f"[info] Loaded {len(source_dataset)} source rows from {args.input_dataset}")
    print(f"[info] Loaded {len(instance_ids)} target instance IDs from {args.task_list_json}")

    filtered = source_dataset.filter(lambda row: row.get("instance_id") in id_set)
    if len(filtered) == 0:
        print(f"[skip] No instances matched in the source dataset for task '{args.task_type}'; nothing to export.")
        return

    filtered = filtered.map(lambda row: {"_repomirage_rank": id_rank[row["instance_id"]]})
    filtered = filtered.sort("_repomirage_rank")
    filtered = filtered.remove_columns(["_repomirage_rank"])

    if "problem_statement" in filtered.column_names:
        prompt = read_problem_statement(args)
        if prompt is None:
            filtered = filtered.map(
                lambda row: {"problem_statement": f"<task>\n\n{row['problem_statement']}\n\n</task>\n\n"}
            )
        else:
            filtered = filtered.map(lambda _: {"problem_statement": prompt})
    else:
        print("[warn] Column 'problem_statement' not found; leaving dataset text unchanged.")

    update_fields = {"repomirage_task_type": args.task_type}
    if args.image_tag:
        update_fields["image_name"] = None
        update_fields["docker_image"] = None

        def add_runtime_fields(row: dict[str, Any]) -> dict[str, Any]:
            image = instance_id_to_image(row["instance_id"], args.image_tag, args.image_prefix)
            return {
                "repomirage_task_type": args.task_type,
                "image_name": image,
                "docker_image": image,
            }
    else:

        def add_runtime_fields(row: dict[str, Any]) -> dict[str, Any]:
            return {"repomirage_task_type": args.task_type}

    filtered = filtered.map(add_runtime_fields)

    output_dir = Path(args.output_dir)
    if output_dir.exists() and not args.overwrite:
        raise FileExistsError(f"Output directory already exists: {output_dir}. Pass --overwrite to replace it.")
    if output_dir.exists():
        shutil.rmtree(output_dir)

    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = data_dir / f"{args.output_split}.parquet"
    filtered.to_parquet(str(parquet_path))

    info_path = output_dir / "dataset_info.json"
    info_path.write_text(json.dumps(dataset_info_to_dict(filtered.info), ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    metadata = {
        "task_type": args.task_type,
        "input_dataset": args.input_dataset,
        "source_split": args.split,
        "output_split": args.output_split,
        "task_list_json": str(args.task_list_json),
        "row_count": len(filtered),
        "image_tag": args.image_tag,
        "image_prefix": args.image_prefix,
    }
    (output_dir / "repomirage_dataset_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if args.push_to_hub:
        DatasetDict({args.output_split: filtered}).push_to_hub(args.push_to_hub, private=args.private)

    print(f"[done] Wrote {len(filtered)} rows to {output_dir}")
    print(f"[done] Parquet: {parquet_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract a RepoMirage task list into a local Hugging Face dataset.")
    parser.add_argument("--input-dataset", required=True, help="Source SWE-bench dataset path or HF dataset name.")
    parser.add_argument("--task-list-json", required=True, help="JSON list produced by summary.py.")
    parser.add_argument("--output-dir", required=True, help="Output local HF dataset directory.")
    parser.add_argument(
        "--task-type",
        required=True,
        choices=sorted(BUILTIN_PROMPTS),
        help="Task family used for the built-in prompt and metadata field.",
    )
    parser.add_argument("--split", default="test", help="Source dataset split. Default: test.")
    parser.add_argument("--output-split", default="test", help="Output parquet split name. Default: test.")
    parser.add_argument("--problem-statement", help="Inline replacement problem statement.")
    parser.add_argument("--problem-statement-file", help="File containing replacement problem statement.")
    parser.add_argument("--image-tag", help="Docker image tag for this task family.")
    parser.add_argument("--image-prefix", default=IMAGE_PREFIX)
    parser.add_argument("--push-to-hub", help="Optional HF Hub dataset repo id.")
    parser.add_argument("--private", action="store_true", help="Create a private dataset when pushing to the Hub.")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    build_dataset(parse_args())


if __name__ == "__main__":
    main()
