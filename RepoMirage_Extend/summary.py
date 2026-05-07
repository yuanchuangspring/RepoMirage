from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_METADATA_DIR = "repomirage_metadata"
DEFAULT_OUTPUT_DIR = "repomirage_metadata_stats_0414"
DEFAULT_PROXY_TOP_K = 144
DEFAULT_CONSTANT_TOP_K = 144


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dedupe_preserve_order(items: List[str]) -> List[str]:
    seen = set()
    output: List[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            output.append(item)
    return output


def summarize_instance(metadata: Dict[str, Any]) -> Dict[str, Any]:
    if "proxy_count" in metadata and "extracted_constant_count" in metadata and "sample" not in metadata:
        return {
            "instance_id": metadata.get("instance_id"),
            "repo_name": metadata.get("repo_name"),
            "patch_touched_files": [],
            "touched_file_count": 0,
            "proxy_count": int(metadata.get("proxy_count", 0)),
            "proxy_files": [],
            "extracted_constant_count": int(metadata.get("extracted_constant_count", 0)),
            "inplace_hiding_applied": False,
            "fake_file_count": 0,
            "fake_files": [],
            "middle_layer_candidate_count": 0,
            "middle_layer_candidates": [],
            "max_proxy_depth": 0,
            "avg_proxy_depth": 0.0,
        }

    sample = metadata.get("sample", {})
    files = metadata.get("files", [])

    proxy_files: List[str] = []
    extracted_constants = int(metadata.get("extracted_constant_count", 0))
    inplace_hiding_applied = False
    fake_files: List[str] = []
    middle_layer_candidates: List[str] = []
    proxy_depths: List[int] = []

    for file_record in files:
        perturbations = file_record.get("perturbations", {})

        proxy_import = perturbations.get("proxy_import", {})
        proxy_files.extend(proxy_import.get("created_proxy_files", []))
        for mapping in proxy_import.get("proxy_mappings", []):
            middle_layer_candidates.extend(mapping.get("middle_layer_candidates", []))
            depth = mapping.get("proxy_depth")
            if isinstance(depth, int):
                proxy_depths.append(depth)
            else:
                chain = mapping.get("proxy_chain", [])
                if isinstance(chain, list) and chain:
                    proxy_depths.append(len(chain))

        if "extracted_constant_count" not in metadata:
            dynamic_dependency = perturbations.get("dynamic_dependency", {})
            extracted_constants += len(dynamic_dependency.get("extracted_constants", []))

        in_place_hiding = perturbations.get("in_place_hiding", {})
        inplace_hiding_applied = inplace_hiding_applied or bool(in_place_hiding.get("whether_applied", False))

        fake_file_meta = perturbations.get("fake_files", {})
        fake_files.extend(fake_file_meta.get("fake_file_paths", []))

    proxy_files = dedupe_preserve_order(proxy_files)
    fake_files = dedupe_preserve_order(fake_files)
    middle_layer_candidates = dedupe_preserve_order(middle_layer_candidates)
    proxy_count = int(metadata.get("proxy_count", len(proxy_files)))
    avg_proxy_depth = round(sum(proxy_depths) / len(proxy_depths), 3) if proxy_depths else 0.0

    return {
        "instance_id": sample.get("instance_id"),
        "repo_name": sample.get("repo_name"),
        "patch_touched_files": sample.get("patch_touched_files", []),
        "touched_file_count": len(sample.get("patch_touched_files", [])),
        "proxy_count": proxy_count,
        "proxy_files": proxy_files,
        "extracted_constant_count": extracted_constants,
        "inplace_hiding_applied": inplace_hiding_applied,
        "fake_file_count": len(fake_files),
        "fake_files": fake_files,
        "middle_layer_candidate_count": len(middle_layer_candidates),
        "middle_layer_candidates": middle_layer_candidates,
        "max_proxy_depth": max(proxy_depths) if proxy_depths else 0,
        "avg_proxy_depth": avg_proxy_depth,
    }


def load_instance_filter(instance_ids_file: Optional[str]) -> Optional[set[str]]:
    if not instance_ids_file:
        return None
    ids = {
        line.strip()
        for line in Path(instance_ids_file).read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    return ids or None


def rank_instances(
    summaries: List[Dict[str, Any]],
    metric_key: str,
) -> List[Dict[str, Any]]:
    return sorted(
        summaries,
        key=lambda item: (-item.get(metric_key, 0), item.get("instance_id", "")),
    )


def assign_ranks(
    summaries: List[Dict[str, Any]],
    ranked: List[Dict[str, Any]],
    rank_field: str,
) -> None:
    for rank, item in enumerate(ranked, start=1):
        item[rank_field] = rank


def build_groups(
    summaries: List[Dict[str, Any]],
    *,
    proxy_top_k: int,
    constant_top_k: int,
) -> Dict[str, List[Dict[str, Any]]]:
    proxy_ranked = rank_instances(summaries, "proxy_count")
    constant_ranked = rank_instances(summaries, "extracted_constant_count")
    touched_ranked = rank_instances(summaries, "touched_file_count")

    assign_ranks(summaries, proxy_ranked, "proxy_rank")
    assign_ranks(summaries, constant_ranked, "constant_rank")
    assign_ranks(summaries, touched_ranked, "touched_files_rank")

    proxy_top_ids = {item["instance_id"] for item in proxy_ranked[:proxy_top_k]}
    constant_top_ids = {item["instance_id"] for item in constant_ranked[:constant_top_k]}
    touched_group_ids = {
        item["instance_id"]
        for item in summaries
        if int(item.get("touched_file_count", 0)) > 1
    }

    assigned_group: Dict[str, str] = {}

    # Assignment priority: touched_files(touched_file_count > 1) > proxy > constant.
    for instance_id in touched_group_ids:
        assigned_group[instance_id] = "touched_files"
    for instance_id in proxy_top_ids:
        if instance_id not in assigned_group:
            assigned_group[instance_id] = "proxy"
    for instance_id in constant_top_ids:
        if instance_id not in assigned_group:
            assigned_group[instance_id] = "constant"

    def backfill(group_name: str, ranked_items: List[Dict[str, Any]], target_size: int) -> None:
        current = sum(1 for value in assigned_group.values() if value == group_name)
        if current >= target_size:
            return
        for item in ranked_items:
            instance_id = item["instance_id"]
            if instance_id in assigned_group:
                continue
            assigned_group[instance_id] = group_name
            current += 1
            if current >= target_size:
                return

    backfill("proxy", proxy_ranked, proxy_top_k)
    backfill("constant", constant_ranked, constant_top_k)

    proxy_group: List[Dict[str, Any]] = []
    constant_group: List[Dict[str, Any]] = []
    touched_group: List[Dict[str, Any]] = []
    remainder_group: List[Dict[str, Any]] = []

    for item in summaries:
        group_name = assigned_group.get(item["instance_id"], "remainder")
        item["assigned_group"] = group_name
        if group_name == "proxy":
            proxy_group.append(item)
        elif group_name == "constant":
            constant_group.append(item)
        elif group_name == "touched_files":
            touched_group.append(item)
        else:
            remainder_group.append(item)

    proxy_group.sort(key=lambda item: (item["proxy_rank"], item["instance_id"]))
    constant_group.sort(key=lambda item: (item["constant_rank"], item["instance_id"]))
    touched_group.sort(key=lambda item: (item["touched_files_rank"], item["instance_id"]))
    remainder_group.sort(
        key=lambda item: (
            -max(
                item.get("proxy_count", 0),
                item.get("extracted_constant_count", 0),
                item.get("touched_file_count", 0),
            ),
            item["instance_id"],
        )
    )

    return {
        "proxy": proxy_group,
        "constant": constant_group,
        "touched_files": touched_group,
        "remainder": remainder_group,
    }


def summarize_metadata_dir(
    metadata_dir: Path,
    output_dir: Path,
    *,
    instance_filter: Optional[set[str]] = None,
    proxy_top_k: int = DEFAULT_PROXY_TOP_K,
    constant_top_k: int = DEFAULT_CONSTANT_TOP_K,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_index: List[Dict[str, Any]] = []
    for metadata_path in sorted(metadata_dir.glob("*.json")):
        instance_id = metadata_path.stem
        if instance_filter is not None and instance_id not in instance_filter:
            continue

        metadata = load_json(metadata_path)
        instance_summary = summarize_instance(metadata)
        summary_index.append(instance_summary)

    groups = build_groups(
        summary_index,
        proxy_top_k=proxy_top_k,
        constant_top_k=constant_top_k,
    )

    for instance_summary in summary_index:
        out_path = output_dir / f"{instance_summary['instance_id']}.json"
        out_path.write_text(json.dumps(instance_summary, ensure_ascii=False, indent=2), encoding="utf-8")

    (output_dir / "summary_index.json").write_text(
        json.dumps(summary_index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / f"proxy_top_{proxy_top_k}.json").write_text(
        json.dumps(groups["proxy"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / f"constant_top_{constant_top_k}.json").write_text(
        json.dumps(groups["constant"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    touched_multi_file_count = len(groups["touched_files"])
    (output_dir / f"touched_files_gt1_{touched_multi_file_count}.json").write_text(
        json.dumps(groups["touched_files"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "remainder.json").write_text(
        json.dumps(groups["remainder"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "group_summary.json").write_text(
        json.dumps(
            {
                "touched_files_rule": "touched_file_count > 1",
                "proxy_top_k": proxy_top_k,
                "constant_top_k": constant_top_k,
                "proxy_group_size": len(groups["proxy"]),
                "constant_group_size": len(groups["constant"]),
                "touched_files_group_size": len(groups["touched_files"]),
                "remainder_group_size": len(groups["remainder"]),
                "total_instances": len(summary_index),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize RepoMirage metadata per instance.")
    parser.add_argument("--metadata-dir", default=DEFAULT_METADATA_DIR)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--instance-ids-file", help="Optional text file with one instance_id per line.")
    parser.add_argument("--proxy-top-k", type=int, default=DEFAULT_PROXY_TOP_K)
    parser.add_argument("--constant-top-k", type=int, default=DEFAULT_CONSTANT_TOP_K)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    metadata_dir = Path(args.metadata_dir)
    if not metadata_dir.exists():
        raise FileNotFoundError(f"Metadata directory not found: {metadata_dir}")

    summarize_metadata_dir(
        metadata_dir=metadata_dir,
        output_dir=Path(args.output_dir),
        instance_filter=load_instance_filter(args.instance_ids_file),
        proxy_top_k=args.proxy_top_k,
        constant_top_k=args.constant_top_k,
    )


if __name__ == "__main__":
    main()
