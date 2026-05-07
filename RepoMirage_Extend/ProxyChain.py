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


DEFAULT_PROXY_TOP_JSON = "repomirage_metadata_stats_0414/proxy_top_144.json"
DEFAULT_METADATA_DIR = "repomirage_metadata"
DEFAULT_SOURCE_TAG = "repomirage_0408"
DEFAULT_TARGET_TAG = "repomirage_0408_task2"
DEFAULT_SUMMARY_PATH = "middle_layer_injection_summary.json"
DEFAULT_GIT_USER_NAME = "RepoMirage"
DEFAULT_GIT_USER_EMAIL = "repomirage@example.invalid"
DEFAULT_COMMIT_MESSAGE = "Initialize proxy-chain task image"
REPO_PREFIX = "swebench/sweb.eval.x86_64."


def load_json(path: str | Path) -> Any:
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8"))


def instance_id_to_repo(instance_id: str) -> str:
    docker_compatible = instance_id.replace("__", "_1776_")
    return f"{REPO_PREFIX}{docker_compatible}"


def stem_from_path(path: str) -> str:
    return Path(path).stem


def collect_middle_layer_candidate_paths(metadata: dict[str, Any]) -> list[str]:
    name_to_path: dict[str, str] = {}
    candidate_names: list[str] = []
    candidate_dirs: list[str] = []

    for file_record in metadata.get("files", []):
        perturbations = file_record.get("perturbations", {})
        proxy_meta = perturbations.get("proxy_import", {})

        for path in proxy_meta.get("created_proxy_files", []):
            name_to_path[stem_from_path(path)] = path

        for mapping in proxy_meta.get("proxy_mappings", []):
            proxy_path = mapping.get("proxy_file_path")
            if proxy_path:
                name_to_path[stem_from_path(proxy_path)] = proxy_path
                candidate_dirs.append(str(Path(proxy_path).parent))
            for candidate in mapping.get("middle_layer_candidates", []):
                if isinstance(candidate, str) and candidate:
                    candidate_names.append(candidate)

    deduped_paths: list[str] = []
    seen: set[str] = set()
    candidate_dirs = list(dict.fromkeys(candidate_dirs))
    for candidate in candidate_names:
        path = name_to_path.get(candidate)
        if not path:
            for directory in candidate_dirs:
                guessed = str(Path(directory) / f"{candidate}.py")
                path = guessed
                break
        if not path or path in seen:
            continue
        seen.add(path)
        deduped_paths.append(path)
    return deduped_paths


def choose_two_candidates(candidate_paths: list[str], rng: random.Random) -> list[str]:
    if len(candidate_paths) < 3:
        return sorted(rng.sample(candidate_paths, len(candidate_paths)))
    return sorted(rng.sample(candidate_paths, 3))


def overwrite_proxy_with_placeholder(container, path: str) -> None:
    command = (
        "python - <<'PY'\n"
        "from pathlib import Path\n"
        f"Path({path!r}).write_text('# <YOUR CODE HERE>\\n', encoding='utf-8')\n"
        "PY"
    )
    result = container.exec_run(
        ["bash", "-lc", command],
        user="root",
        workdir="/testbed",
    )
    if result.exit_code != 0:
        raise RuntimeError(result.output.decode("utf-8", errors="ignore"))


def apply_instance_injection(
    client: docker.DockerClient,
    *,
    instance_id: str,
    metadata_path: Path,
    source_tag: str,
    target_tag: str,
    rng: random.Random,
    overwrite: bool,
    git_user_name: str,
    git_user_email: str,
    commit_message: str,
) -> dict[str, Any]:
    metadata = load_json(metadata_path)
    candidate_paths = collect_middle_layer_candidate_paths(metadata)
    chosen_paths = choose_two_candidates(candidate_paths, rng)
    if len(chosen_paths) < 3:
        return {
            "instance_id": instance_id,
            "status": "skipped_not_enough_candidates",
            "candidate_count": len(candidate_paths),
            "chosen_paths": chosen_paths,
        }

    repo = instance_id_to_repo(instance_id)
    source_image = f"{repo}:{source_tag}"
    target_image = f"{repo}:{target_tag}"

    if not overwrite:
        try:
            client.images.get(target_image)
            return {
                "instance_id": instance_id,
                "status": "skipped_target_exists",
                "candidate_count": len(candidate_paths),
                "chosen_paths": chosen_paths,
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

        for proxy_path in chosen_paths:
            overwrite_proxy_with_placeholder(container, proxy_path)

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
            "candidate_count": len(candidate_paths),
            "chosen_paths": chosen_paths,
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
        description="Blank selected middle-layer proxy files for each instance in a proxy-top list and commit a new image tag."
    )
    parser.add_argument("--proxy-top-json", default=DEFAULT_PROXY_TOP_JSON)
    parser.add_argument("--metadata-dir", default=DEFAULT_METADATA_DIR)
    parser.add_argument("--source-tag", default=DEFAULT_SOURCE_TAG)
    parser.add_argument("--target-tag", default=DEFAULT_TARGET_TAG)
    parser.add_argument("--summary-path", default=DEFAULT_SUMMARY_PATH)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--git-user-name", default=DEFAULT_GIT_USER_NAME)
    parser.add_argument("--git-user-email", default=DEFAULT_GIT_USER_EMAIL)
    parser.add_argument("--commit-message", default=DEFAULT_COMMIT_MESSAGE)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    proxy_top_json = Path(args.proxy_top_json)
    metadata_dir = Path(args.metadata_dir)
    summary_path = Path(args.summary_path)

    if not proxy_top_json.exists():
        raise FileNotFoundError(f"Proxy-top JSON not found: {proxy_top_json}")
    if not metadata_dir.exists():
        raise FileNotFoundError(f"Metadata directory not found: {metadata_dir}")
    if docker is None:
        raise RuntimeError("Missing Python package 'docker'. Install it first, for example: pip install docker")

    data = load_json(proxy_top_json)
    if not isinstance(data, list):
        raise ValueError(f"Expected a list in {proxy_top_json}")

    instance_ids: list[str] = []
    for item in data:
        if isinstance(item, dict) and item.get("instance_id"):
            instance_ids.append(item["instance_id"])
        elif isinstance(item, str):
            instance_ids.append(item)

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
        print(json.dumps(result, ensure_ascii=False))

    summary = {
        "proxy_top_json": str(proxy_top_json),
        "metadata_dir": str(metadata_dir),
        "source_tag": args.source_tag,
        "target_tag": args.target_tag,
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
