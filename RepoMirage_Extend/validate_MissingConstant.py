from __future__ import annotations

import argparse
import io
import json
import sys
import tarfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from repomirage_common import REPORTS_DIR  # noqa: E402

try:
    import docker
except ModuleNotFoundError:
    docker = None


DEFAULT_REPORT_PATH = str(REPORTS_DIR / "missing_constant_validation_report.json")


def load_json(path: str | Path) -> Any:
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_solutions(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        normalized: list[dict[str, Any]] = []
        for instance_id, item in payload.items():
            if not isinstance(item, dict):
                continue
            entry = dict(item)
            entry.setdefault("instance_id", instance_id)
            normalized.append(entry)
        return normalized
    raise ValueError("solutions_json must contain either a JSON list or a JSON object keyed by instance_id")


def build_feedback_index(feedback: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for item in feedback.get("results", []):
        instance_id = item.get("instance_id")
        if instance_id:
            index[instance_id] = item
    return index


def find_solution_patch(item: dict[str, Any]) -> str:
    for key in ("patch", "agent_patch", "completion_patch", "model_patch"):
        value = item.get(key)
        if isinstance(value, str):
            return value
    return ""


def copy_text_file_to_container(
    container: docker.models.containers.Container,
    *,
    content: str,
    container_path: str,
) -> None:
    tar_bytes = io.BytesIO()
    with tarfile.open(fileobj=tar_bytes, mode="w") as tar:
        data = content.encode("utf-8")
        info = tarfile.TarInfo(name=Path(container_path).name)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    tar_bytes.seek(0)
    parent = Path(container_path).parent.as_posix()
    container.exec_run(f"mkdir -p {parent}", user="root")
    container.put_archive(parent, tar_bytes.read())


def apply_patch_in_container(
    container: docker.models.containers.Container,
    *,
    patch_text: str,
) -> tuple[bool, str]:
    container_patch_path = "/tmp/agent_patch.diff"
    copy_text_file_to_container(container, content=patch_text, container_path=container_patch_path)
    result = container.exec_run(
        f"git apply --whitespace=nowarn {container_patch_path}",
        workdir="/testbed",
        user="root",
    )
    output = result.output.decode("utf-8", errors="ignore")
    return result.exit_code == 0, output


def run_validation_script(
    container: docker.models.containers.Container,
    *,
    validation_script: str,
) -> tuple[bool, dict[str, Any] | str]:
    command = ["bash", "-lc", f"python - <<'PY'\n{validation_script}\nPY"]
    result = container.exec_run(command, user="root", workdir="/testbed")
    output = result.output.decode("utf-8", errors="ignore")
    if result.exit_code != 0:
        return False, output
    try:
        payload = json.loads(output.strip().splitlines()[-1])
    except Exception:
        return False, f"non_json_output: {output}"
    return bool(payload.get("ok", False)), payload


def validate_instance(
    client: docker.DockerClient,
    *,
    solution: dict[str, Any],
    feedback_entry: dict[str, Any],
) -> dict[str, Any]:
    instance_id = solution.get("instance_id")
    if not instance_id:
        return {"instance_id": None, "status": "invalid_solution_entry", "reason": "missing_instance_id"}

    patch_text = find_solution_patch(solution)
    if not patch_text:
        return {"instance_id": instance_id, "status": "invalid_solution_entry", "reason": "missing_patch"}

    target_image = feedback_entry.get("target_image")
    if not target_image:
        return {"instance_id": instance_id, "status": "missing_target_image"}

    validation_script = feedback_entry.get("validation_script")
    if not isinstance(validation_script, str) or not validation_script.strip():
        return {"instance_id": instance_id, "status": "missing_validation_script"}

    container = None
    try:
        container = client.containers.run(
            target_image,
            command="sleep infinity",
            user="root",
            detach=True,
            init=True,
        )

        apply_ok, apply_output = apply_patch_in_container(container, patch_text=patch_text)
        if not apply_ok:
            return {
                "instance_id": instance_id,
                "status": "patch_apply_failed",
                "target_image": target_image,
                "apply_output": apply_output,
            }

        ok, payload = run_validation_script(container, validation_script=validation_script)
        return {
            "instance_id": instance_id,
            "status": "qualified" if ok else "unqualified",
            "target_image": target_image,
            "validation_result": payload,
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
        description="Validate agent repairs for blanked constant JSON keys using stored validation scripts."
    )
    parser.add_argument("solutions_json", help="JSON file containing agent solutions keyed by instance or as a list.")
    parser.add_argument(
        "feedback_json",
        help="Generation summary produced by MissingConstant.py (missing_constant_generation_summary.json).",
    )
    parser.add_argument("--report-path", default=DEFAULT_REPORT_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if docker is None:
        raise RuntimeError("Missing Python package 'docker'. Install it first, for example: pip install docker")
    solutions = normalize_solutions(load_json(args.solutions_json))
    feedback = load_json(args.feedback_json)
    feedback_index = build_feedback_index(feedback)

    client = docker.from_env()
    results: list[dict[str, Any]] = []

    for solution in solutions:
        instance_id = solution.get("instance_id")
        feedback_entry = feedback_index.get(instance_id)
        if feedback_entry is None:
            result = {"instance_id": instance_id, "status": "missing_feedback_entry"}
        else:
            result = validate_instance(
                client,
                solution=solution,
                feedback_entry=feedback_entry,
            )
        results.append(result)
        print(json.dumps(result, ensure_ascii=False))

    qualified = [item["instance_id"] for item in results if item.get("status") == "qualified"]
    unqualified = [item["instance_id"] for item in results if item.get("status") != "qualified"]
    report = {
        "qualified_count": len(qualified),
        "unqualified_count": len(unqualified),
        "qualified_instance_ids": qualified,
        "unqualified_instance_ids": unqualified,
        "results": results,
    }
    Path(args.report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved report to: {args.report_path}")


if __name__ == "__main__":
    main()
