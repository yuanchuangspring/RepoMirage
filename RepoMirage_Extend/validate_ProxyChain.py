from __future__ import annotations

import argparse
import ast
import io
import json
import re
import sys
import tarfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from repomirage_common import METADATA_DIR, REPORTS_DIR  # noqa: E402

try:
    import docker
except ModuleNotFoundError:
    docker = None


PATCH_FILE_RE = re.compile(r"^diff --git a/(.*?) b/(.*?)\s*$", re.MULTILINE)
DEFAULT_METADATA_DIR = str(METADATA_DIR)
DEFAULT_REPORT_PATH = str(REPORTS_DIR / "proxy_chain_validation_report.json")


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


def instance_id_to_repo(instance_id: str) -> str:
    docker_compatible = instance_id.replace("__", "_1776_")
    return f"swebench/sweb.eval.x86_64.{docker_compatible}"


def extract_patch_files(patch_text: str) -> list[str]:
    files = [b_path for _, b_path in PATCH_FILE_RE.findall(patch_text)]
    seen: set[str] = set()
    ordered: list[str] = []
    for path in files:
        if path not in seen:
            seen.add(path)
            ordered.append(path)
    return ordered


def build_feedback_index(feedback: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], str | None]:
    target_tag = feedback.get("target_tag")
    # target_tag = "solut"
    index: dict[str, dict[str, Any]] = {}
    for item in feedback.get("results", []):
        instance_id = item.get("instance_id")
        if instance_id:
            index[instance_id] = item
    return index, target_tag


def find_solution_patch(item: dict[str, Any]) -> str:
    for key in ("patch", "agent_patch", "completion_patch", "model_patch"):
        value = item.get(key)
        if isinstance(value, str):
            return value
    return ""


def choose_target_mappings(metadata: dict[str, Any], chosen_paths: list[str]) -> list[dict[str, Any]]:
    chosen_names = {Path(path).stem for path in chosen_paths}
    selected: list[dict[str, Any]] = []
    for file_record in metadata.get("files", []):
        runtime_real_file = file_record.get("runtime_real_file")
        proxy_mappings = file_record.get("perturbations", {}).get("proxy_import", {}).get("proxy_mappings", [])
        all_runtime_targets = [
            target
            for target in (mapping.get("runtime_real_target") for mapping in proxy_mappings)
            if isinstance(target, str) and target
        ]
        file_selected = []
        for mapping in proxy_mappings:
            middle = set(mapping.get("middle_layer_candidates", []))
            if chosen_names & middle:
                file_selected.append(mapping)
        if file_selected and runtime_real_file:
            selected.append(
                {
                    "runtime_real_file": runtime_real_file,
                    "mappings": file_selected,
                    "all_runtime_targets": list(dict.fromkeys(all_runtime_targets)),
                }
            )
    return selected


def validate_patch_scope(
    patch_text: str,
    *,
    allowed_paths: list[str],
) -> tuple[bool, dict[str, Any]]:
    touched_files = extract_patch_files(patch_text)
    allowed_set = set[str](allowed_paths)
    invalid = [path for path in touched_files if path not in allowed_set]
    return (
        len(invalid) == 0 and len(touched_files) > 0,
        # True,
        {
            "touched_files": touched_files,
            "allowed_paths": allowed_paths,
            "invalid_paths": invalid,
        },
    )


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
    container.exec_run(f"mkdir -p {Path(container_path).parent.as_posix()}", user="root")
    container.put_archive(Path(container_path).parent.as_posix(), tar_bytes.read())


def build_test_proxy_script(
    runtime_real_file: str,
    mappings: list[dict[str, Any]],
    all_runtime_targets: list[str] | None = None,
) -> str:
    imports = []
    checks = []
    expected_targets: list[str] = []
    for mapping in mappings:
        alias = mapping.get("affected_symbols", {}).get("rewritten_alias")
        if not alias:
            continue
        expected = mapping.get("runtime_real_target", "")
        rewritten_import = mapping.get("rewritten_import", "")
        if rewritten_import:
            imports.append(rewritten_import)
        if expected:
            expected_targets.append(expected)
        checks.append(
            {
                "alias": alias,
                "expected": expected,
                "original_dependency": mapping.get("original_dependency"),
            }
        )
    if all_runtime_targets:
        expected_targets.extend(
            target for target in all_runtime_targets if isinstance(target, str) and target
        )
    expected_targets = list(dict.fromkeys(expected_targets))
    target_dir = str(Path(runtime_real_file).parent)

    script = f"""import os
import sys
from unittest.mock import MagicMock

_TARGET_DIR = {target_dir!r}
if _TARGET_DIR not in sys.path:
    sys.path.append(_TARGET_DIR)

EXPECTED_TARGETS = {expected_targets!r}

def _install_mock_module(fullname):
    parts = fullname.split(".")
    parent = None
    built = []
    for part in parts:
        built.append(part)
        current_name = ".".join(built)
        module = sys.modules.get(current_name)
        if module is None:
            module = MagicMock(name=current_name)
            module.__name__ = current_name
            module.__package__ = current_name.rsplit(".", 1)[0] if "." in current_name else ""
            module.__file__ = f"/mocked/{{current_name.replace('.', '/')}}.py"
            sys.modules[current_name] = module
        if parent is not None:
            setattr(parent, part, module)
        parent = module

for _target in EXPECTED_TARGETS:
    _install_mock_module(_target)

{chr(10).join(imports)}

CHECKS = {checks!r}

def _matches(obj, expected):
    name = getattr(obj, "__name__", None)
    package = getattr(obj, "__package__", None)
    file_path = getattr(obj, "__file__", None)
    if name == expected or (isinstance(name, str) and name.startswith(expected + ".")):
        return True
    if package == expected or (isinstance(package, str) and package.startswith(expected + ".")):
        return True
    if isinstance(file_path, str):
        target_fragment = expected.replace(".", os.sep)
        if target_fragment and target_fragment in file_path:
            return True
    return False

results = []
all_ok = True
for item in CHECKS:
    alias = item["alias"]
    expected = item["expected"]
    if alias not in globals():
        results.append({{"alias": alias, "expected": expected, "ok": False, "reason": "missing_alias"}})
        all_ok = False
        continue
    obj = globals()[alias]
    ok = _matches(obj, expected)
    results.append({{
        "alias": alias,
        "expected": expected,
        "ok": ok,
        "observed_name": getattr(obj, "__name__", None),
        "observed_package": getattr(obj, "__package__", None),
        "observed_file": getattr(obj, "__file__", None),
    }})
    if not ok:
        all_ok = False

print(repr({{"all_ok": all_ok, "results": results}}))
"""

    return script


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


def run_proxy_test(
    container: docker.models.containers.Container,
    *,
    runtime_real_file: str,
    mappings: list[dict[str, Any]],
    all_runtime_targets: list[str] | None = None,
) -> dict[str, Any]:
    runtime_dir = str(Path(runtime_real_file).parent)
    test_name = f"test_proxy_{Path(runtime_real_file).stem.replace('.', '_')}.py"
    test_path = str(Path("/tmp") / test_name)
    script = build_test_proxy_script(runtime_real_file, mappings, all_runtime_targets)
    copy_text_file_to_container(container, content=script, container_path=test_path)
    result = container.exec_run(f"python {test_path}", workdir="/testbed", user="root")
    output = result.output.decode("utf-8", errors="ignore")
    if result.exit_code != 0:
        return {
            "runtime_real_file": runtime_real_file,
            "ok": False,
            "error": output,
        }
    payload_text = output.strip().splitlines()[-1] if output.strip() else ""
    try:
        payload = json.loads(payload_text)
    except Exception:
        try:
            payload = ast.literal_eval(payload_text)
        except Exception:
            return {
                "runtime_real_file": runtime_real_file,
                "ok": False,
                "error": f"non_json_output: {output}",
            }
    return {
        "runtime_real_file": runtime_real_file,
        "ok": bool(payload.get("all_ok", False)),
        "results": payload.get("results", []),
    }


def validate_instance(
    client: docker.DockerClient,
    *,
    solution: dict[str, Any],
    feedback_entry: dict[str, Any],
    feedback_target_tag: str | None,
    metadata_dir: Path,
) -> dict[str, Any]:
    instance_id = solution.get("instance_id")
    patch_text = find_solution_patch(solution)
    if not instance_id:
        return {"instance_id": None, "status": "invalid_solution_entry", "reason": "missing_instance_id"}
    if not patch_text:
        return {"instance_id": instance_id, "status": "invalid_solution_entry", "reason": "missing_patch"}

    metadata_path = metadata_dir / f"{instance_id}.json"
    if not metadata_path.exists():
        return {"instance_id": instance_id, "status": "missing_metadata", "metadata_path": str(metadata_path)}

    chosen_paths = feedback_entry.get("chosen_paths", [])
    if not isinstance(chosen_paths, list) or not chosen_paths:
        return {"instance_id": instance_id, "status": "missing_feedback_candidates"}

    metadata = load_json(metadata_path)
    repo_root = metadata.get("sample", {}).get("repo_path", "/testbed")
    allowed_paths = [
        str(Path(path).relative_to(repo_root))
        if str(path).startswith(repo_root.rstrip("/") + "/")
        else path
        for path in chosen_paths
    ]
    patch_scope_ok, scope_info = validate_patch_scope(patch_text, allowed_paths=allowed_paths)
    if not patch_scope_ok:
        return {
            "instance_id": instance_id,
            "status": "invalid_patch_scope",
            **scope_info,
        }

    target_image = feedback_entry.get("target_image")
    if not target_image:
        tag = feedback_target_tag
        if not tag:
            return {"instance_id": instance_id, "status": "missing_target_image"}
        target_image = f"{instance_id_to_repo(instance_id)}:{tag}"

    runtime_groups = choose_target_mappings(metadata, chosen_paths)
    if not runtime_groups:
        return {
            "instance_id": instance_id,
            "status": "no_runtime_proxy_mappings",
            "chosen_paths": chosen_paths,
        }

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
                "apply_output": apply_output,
            }

        runtime_checks = []
        all_ok = True
        for group in runtime_groups:
            result = run_proxy_test(
                container,
                runtime_real_file=group["runtime_real_file"],
                mappings=group["mappings"],
                all_runtime_targets=group.get("all_runtime_targets"),
            )
            runtime_checks.append(result)
            if not result.get("ok", False):
                all_ok = False

        return {
            "instance_id": instance_id,
            "status": "qualified" if all_ok else "unqualified",
            "target_image": target_image,
            "chosen_paths": chosen_paths,
            "patch_scope": scope_info,
            "runtime_checks": runtime_checks,
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
    parser = argparse.ArgumentParser(description="Validate agent repairs for blanked middle-layer proxy files.")
    parser.add_argument("solutions_json", help="JSON file containing a list of {instance_id, patch} entries.")
    parser.add_argument(
        "feedback_json",
        help="Generation summary produced by ProxyChain.py (proxy_chain_generation_summary.json).",
    )
    parser.add_argument("--metadata-dir", default=DEFAULT_METADATA_DIR)
    parser.add_argument("--report-path", default=DEFAULT_REPORT_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if docker is None:
        raise RuntimeError("Missing Python package 'docker'. Install it first, for example: pip install docker")
    solutions_payload = load_json(args.solutions_json)
    feedback = load_json(args.feedback_json)
    metadata_dir = Path(args.metadata_dir)

    solutions = normalize_solutions(solutions_payload)
    if not metadata_dir.exists():
        raise FileNotFoundError(f"Metadata directory not found: {metadata_dir}")

    feedback_index, feedback_target_tag = build_feedback_index(feedback)
    client = docker.from_env()
    results = []

    for solution in solutions:
        if not isinstance(solution, dict):
            results.append({"instance_id": None, "status": "invalid_solution_entry", "reason": "not_an_object"})
            continue
        instance_id = solution.get("instance_id")
        feedback_entry = feedback_index.get(instance_id)
        if feedback_entry is None:
            results.append({"instance_id": instance_id, "status": "missing_feedback_entry"})
            continue
        result = validate_instance(
            client,
            solution=solution,
            feedback_entry=feedback_entry,
            feedback_target_tag=feedback_target_tag,
            metadata_dir=metadata_dir,
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
    report_path = Path(args.report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved report to: {args.report_path}")


if __name__ == "__main__":
    main()
