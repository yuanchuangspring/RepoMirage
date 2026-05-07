from __future__ import annotations

import argparse
import json
import random
import shlex
from pathlib import Path
from typing import Any

try:
    import docker
except ModuleNotFoundError:
    docker = None


DEFAULT_INSTANCES_JSON = "repomirage_metadata_stats_0414/constant_top_144.json"
DEFAULT_METADATA_DIR = "repomirage_metadata"
DEFAULT_SOURCE_TAG = "repomirage_0408"
DEFAULT_TARGET_TAG = "repomirage_0408_task4"
DEFAULT_SUMMARY_PATH = "constant_placeholder_injection_summary.json"
DEFAULT_PLACEHOLDER = "YOUR CODE HERE"
DEFAULT_SAMPLE_SIZE = 5
DEFAULT_GIT_USER_NAME = "RepoMirage"
DEFAULT_GIT_USER_EMAIL = "repomirage@example.invalid"
DEFAULT_COMMIT_MESSAGE = "Initialize missing-constant task image"
REPO_PREFIX = "swebench/sweb.eval.x86_64."


def load_json(path: str | Path) -> Any:
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_instance_ids(payload: Any) -> list[str]:
    if not isinstance(payload, list):
        raise ValueError("instances_json must contain a JSON list")

    instance_ids: list[str] = []
    seen: set[str] = set()
    for item in payload:
        if isinstance(item, dict):
            instance_id = item.get("instance_id")
        elif isinstance(item, str):
            instance_id = item
        else:
            instance_id = None
        if instance_id and instance_id not in seen:
            seen.add(instance_id)
            instance_ids.append(instance_id)
    return instance_ids


def instance_id_to_repo(instance_id: str) -> str:
    docker_compatible = instance_id.replace("__", "_1776_")
    return f"{REPO_PREFIX}{docker_compatible}"


def collect_constant_candidates(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for file_record in metadata.get("files", []):
        dynamic_meta = file_record.get("perturbations", {}).get("dynamic_dependency", {})
        for item in dynamic_meta.get("extracted_constants", []):
            json_path = item.get("json_path")
            json_key = item.get("json_key")
            if not json_path or not json_key:
                continue
            key = (json_path, json_key)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "json_path": json_path,
                    "json_key": json_key,
                    "original_value": item.get("original_value"),
                    "literal_type": item.get("literal_type"),
                    "source_code_location": item.get("source_code_location"),
                    "replacement_expression": item.get("replacement_expression"),
                    "runtime_value_source": item.get("runtime_value_source"),
                }
            )
    return candidates


def choose_constants(
    candidates: list[dict[str, Any]],
    *,
    sample_size: int,
    rng: random.Random,
) -> list[dict[str, Any]]:
    if len(candidates) < sample_size:
        return []
    return sorted(
        rng.sample(candidates, sample_size),
        key=lambda item: (item["json_path"], item["json_key"]),
    )


def assign_placeholder_keys(
    chosen_constants: list[dict[str, Any]],
    *,
    placeholder: str,
) -> list[dict[str, Any]]:
    assigned: list[dict[str, Any]] = []
    for index, item in enumerate(chosen_constants, start=1):
        copied = dict(item)
        copied["placeholder_key"] = f"{placeholder}_{index}"
        assigned.append(copied)

    return assigned


def build_update_script(chosen_constants: list[dict[str, Any]], placeholder: str) -> str:
    payload = json.dumps(chosen_constants, ensure_ascii=False, indent=2)
    return f"""import json
from pathlib import Path

PLACEHOLDER = {placeholder!r}
ITEMS = {payload}

for item in ITEMS:
    path = Path(item["json_path"])
    data = json.loads(path.read_text(encoding="utf-8"))
    if item["json_key"] not in data:
        raise KeyError(f"Missing key: {{item['json_key']}} in {{path}}")
    value = data.pop(item["json_key"])
    data[item["placeholder_key"]] = value
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
"""


def build_validation_script(chosen_constants: list[dict[str, Any]], placeholder: str) -> str:
    payload = json.dumps(
        [
            {
                "json_path": item["json_path"],
                "json_key": item["json_key"],
                "expected_value": item["original_value"],
                "placeholder_key": item["placeholder_key"],
            }
            for item in chosen_constants
        ],
        ensure_ascii=False,
        indent=2,
    )
    return f"""import json
from pathlib import Path

CHECKS = {payload}

def _is_dependency_json(path: Path) -> bool:
    name = path.name
    return name == "dependencies.json" or (
        name.startswith("dependencies_") and name.endswith(".json")
    )

def _load_merged_dependencies(base_dir: Path) -> dict:
    merged = {{}}
    for path in sorted(base_dir.iterdir()):
        if not path.is_file() or not _is_dependency_json(path):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict):
            merged.update(data)
    return merged

failures = []
dir_to_merged = {{}}
for item in CHECKS:
    path = Path(item["json_path"])
    base_dir = path.parent
    if not base_dir.exists():
        failures.append({{"json_path": str(path), "json_key": item["json_key"], "reason": "missing_json_dir"}})
        continue
    base_dir_str = str(base_dir)
    if base_dir_str not in dir_to_merged:
        dir_to_merged[base_dir_str] = _load_merged_dependencies(base_dir)
    merged = dir_to_merged[base_dir_str]

    if item["json_key"] not in merged:
        reason = "missing_original_key"
        if item["placeholder_key"] in merged:
            reason = "placeholder_key_still_present"
        failures.append(
            {{
                "json_path": str(path),
                "json_key": item["json_key"],
                "reason": reason,
                "merged_dir": base_dir_str,
                "placeholder_key": item["placeholder_key"],
            }}
        )
        continue
    if merged[item["json_key"]] != item["expected_value"]:
        failures.append({{
            "json_path": str(path),
            "json_key": item["json_key"],
            "reason": "wrong_value",
            "expected_value": item["expected_value"],
            "actual_value": merged[item["json_key"]],
            "merged_dir": base_dir_str,
        }})

if failures:
    raise SystemExit(json.dumps({{"ok": False, "failures": failures}}, ensure_ascii=False))

print(json.dumps({{"ok": True, "checked": len(CHECKS)}}, ensure_ascii=False))
"""


def run_python_in_container(
    container: docker.models.containers.Container,
    script: str,
) -> tuple[bool, str]:
    command = ["bash", "-lc", f"python - <<'PY'\n{script}\nPY"]
    result = container.exec_run(command, user="root", workdir="/testbed")
    output = result.output.decode("utf-8", errors="ignore")
    return result.exit_code == 0, output


def apply_instance_injection(
    client: docker.DockerClient,
    *,
    instance_id: str,
    metadata_path: Path,
    source_tag: str,
    target_tag: str,
    sample_size: int,
    placeholder: str,
    rng: random.Random,
    overwrite: bool,
    git_user_name: str,
    git_user_email: str,
    commit_message: str,
) -> dict[str, Any]:
    metadata = load_json(metadata_path)
    candidates = collect_constant_candidates(metadata)
    chosen_constants = choose_constants(candidates, sample_size=sample_size, rng=rng)
    if len(chosen_constants) < sample_size:
        return {
            "instance_id": instance_id,
            "status": "skipped_not_enough_constants",
            "candidate_count": len(candidates),
            "required_count": sample_size,
        }
    chosen_constants = assign_placeholder_keys(chosen_constants, placeholder=placeholder)

    repo = instance_id_to_repo(instance_id)
    source_image = f"{repo}:{source_tag}"
    target_image = f"{repo}:{target_tag}"

    if not overwrite:
        try:
            client.images.get(target_image)
            return {
                "instance_id": instance_id,
                "status": "skipped_target_exists",
                "candidate_count": len(candidates),
                "selected_constants": chosen_constants,
                "validation_script": build_validation_script(chosen_constants, placeholder),
                "target_image": target_image,
            }
        except docker.errors.ImageNotFound:
            pass

    container = None
    try:
        container = client.containers.run(
            source_image,
            command="sleep infinity",
            user="root",
            detach=True,
            init=True,
        )

        update_script = build_update_script(chosen_constants, placeholder)
        ok, output = run_python_in_container(container, update_script)
        if not ok:
            raise RuntimeError(f"constant update failed: {output}")

        remove_git_result = container.exec_run("rm -rf /testbed/.git", user="root")
        if remove_git_result.exit_code != 0:
            raise RuntimeError(
                f"failed to remove original .git: {remove_git_result.output.decode('utf-8', errors='ignore')}"
            )

        init_result = container.exec_run("git init", workdir="/testbed")
        if init_result.exit_code != 0:
            raise RuntimeError(f"git init failed: {init_result.output.decode('utf-8', errors='ignore')}")

        container.exec_run("git branch -M main", workdir="/testbed")
        container.exec_run(f"git config user.email {shlex.quote(git_user_email)}", workdir="/testbed")
        container.exec_run(f"git config user.name {shlex.quote(git_user_name)}", workdir="/testbed")

        add_result = container.exec_run("git add -A", workdir="/testbed")
        if add_result.exit_code != 0:
            raise RuntimeError(f"git add failed: {add_result.output.decode('utf-8', errors='ignore')}")

        commit_result = container.exec_run(
            f"git commit -m {shlex.quote(commit_message)}",
            workdir="/testbed",
        )
        commit_output = commit_result.output.decode("utf-8", errors="ignore")
        if commit_result.exit_code != 0 and "nothing to commit" not in commit_output:
            raise RuntimeError(f"git commit failed: {commit_output}")

        image = container.commit(repository=repo, tag=target_tag)
        return {
            "instance_id": instance_id,
            "status": "ok",
            "candidate_count": len(candidates),
            "selected_constants": chosen_constants,
            "validation_script": build_validation_script(chosen_constants, placeholder),
            "source_image": source_image,
            "target_image": target_image,
            "image_id": image.id,
        }
    finally:
        if container is not None:
            try:
                container.kill()
            except Exception:
                pass
            try:
                container.remove()
            except Exception:
                pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replace selected extracted constants in dependency JSON files with placeholders and commit new images."
    )
    parser.add_argument("--instances-json", default=DEFAULT_INSTANCES_JSON)
    parser.add_argument("--metadata-dir", default=DEFAULT_METADATA_DIR)
    parser.add_argument("--source-tag", default=DEFAULT_SOURCE_TAG)
    parser.add_argument("--target-tag", default=DEFAULT_TARGET_TAG)
    parser.add_argument("--summary-path", default=DEFAULT_SUMMARY_PATH)
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE)
    parser.add_argument("--placeholder", default=DEFAULT_PLACEHOLDER)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--git-user-name", default=DEFAULT_GIT_USER_NAME)
    parser.add_argument("--git-user-email", default=DEFAULT_GIT_USER_EMAIL)
    parser.add_argument("--commit-message", default=DEFAULT_COMMIT_MESSAGE)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    instances_json = Path(args.instances_json)
    metadata_dir = Path(args.metadata_dir)
    summary_path = Path(args.summary_path)

    if not instances_json.exists():
        raise FileNotFoundError(f"Instances JSON not found: {instances_json}")
    if not metadata_dir.exists():
        raise FileNotFoundError(f"Metadata directory not found: {metadata_dir}")
    if docker is None:
        raise RuntimeError("Missing Python package 'docker'. Install it first, for example: pip install docker")

    instance_ids = normalize_instance_ids(load_json(instances_json))
    client = docker.from_env()
    rng = random.Random(args.seed)
    results: list[dict[str, Any]] = []

    for instance_id in instance_ids:
        metadata_path = metadata_dir / f"{instance_id}.json"
        if not metadata_path.exists():
            results.append(
                {
                    "instance_id": instance_id,
                    "status": "missing_metadata",
                    "metadata_path": str(metadata_path),
                }
            )
            continue

        try:
            result = apply_instance_injection(
                client,
                instance_id=instance_id,
                metadata_path=metadata_path,
                source_tag=args.source_tag,
                target_tag=args.target_tag,
                sample_size=args.sample_size,
                placeholder=args.placeholder,
                rng=rng,
                overwrite=args.overwrite,
                git_user_name=args.git_user_name,
                git_user_email=args.git_user_email,
                commit_message=args.commit_message,
            )
        except Exception as exc:
            result = {
                "instance_id": instance_id,
                "status": "error",
                "error": str(exc),
            }
        results.append(result)
        print(json.dumps({"instance_id": instance_id, "status": result.get("status")}, ensure_ascii=False))

    summary = {
        "instances_json": str(instances_json),
        "metadata_dir": str(metadata_dir),
        "source_tag": args.source_tag,
        "target_tag": args.target_tag,
        "sample_size": args.sample_size,
        "placeholder": args.placeholder,
        "seed": args.seed,
        "git_user_name": args.git_user_name,
        "git_user_email": args.git_user_email,
        "commit_message": args.commit_message,
        "results": results,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved summary to: {summary_path}")


if __name__ == "__main__":
    main()
