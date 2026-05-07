from __future__ import annotations

import argparse
import hashlib
import json
import random
import shlex
import traceback
from pathlib import Path
from typing import Any

try:
    import docker
except ModuleNotFoundError:
    docker = None


DEFAULT_INSTANCES_JSON = "repomirage_metadata_stats_0414/remainder.json"
DEFAULT_METADATA_DIR = "repomirage_metadata"
DEFAULT_SOURCE_TAG = "repomirage_0408"
DEFAULT_TARGET_TAG = "repomirage_0408_task3"
DEFAULT_SUMMARY_PATH = "wrapper_placeholder_variant_injection_summary_compact.json"
DEFAULT_PLACEHOLDER = "YOUR CODE HERE"
DEFAULT_GIT_USER_NAME = "RepoMirage"
DEFAULT_GIT_USER_EMAIL = "repomirage@example.invalid"
DEFAULT_COMMIT_MESSAGE = "Initialize runtime-target task image"
REPO_PREFIX = "swebench/sweb.eval.x86_64."

NAME_PARTS = [
    "harbor",
    "meadow",
    "signal",
    "cinder",
    "willow",
    "marble",
    "lantern",
    "cedar",
    "ripple",
    "atlas",
    "quartz",
    "hollow",
    "sparrow",
    "drift",
    "orchid",
    "ember",
    "lattice",
    "canyon",
    "shelter",
    "pollen",
    "fable",
    "tidal",
    "parlor",
    "velvet",
    "anchor",
    "grove",
    "meridian",
    "thicket",
    "window",
    "cobalt",
    "tangent",
]


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


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
    return f"{REPO_PREFIX}{instance_id.replace('__', '_1776_')}"


def collect_wrapper_candidates(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for file_record in metadata.get("files", []):
        perturbations = file_record.get("perturbations", {})
        hiding_meta = perturbations.get("in_place_hiding", {})
        fake_meta = perturbations.get("fake_files", {})
        if not hiding_meta.get("whether_applied"):
            continue

        wrapper_init_path = hiding_meta.get("wrapper_init_path")
        runtime_real_file = hiding_meta.get("runtime_real_file") or file_record.get("runtime_real_file")
        hidden_impl_name = hiding_meta.get("wrapper_import_relation", {}).get("hidden_impl_name")
        if not wrapper_init_path or not runtime_real_file or not hidden_impl_name:
            continue

        key = (wrapper_init_path, runtime_real_file)
        if key in seen:
            continue
        seen.add(key)

        candidates.append(
            {
                "wrapper_init_path": wrapper_init_path,
                "runtime_real_file": runtime_real_file,
                "hidden_impl_name": hidden_impl_name,
                "fake_file_paths": [
                    path for path in fake_meta.get("fake_file_paths", []) if isinstance(path, str) and path
                ],
            }
        )
    return candidates


def _local_rng(seed: int, *parts: str) -> random.Random:
    digest = hashlib.sha1("::".join([str(seed), *parts]).encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def _draw_name(rng: random.Random, used_names: set[str]) -> str:
    while True:
        candidate = "_".join(rng.sample(NAME_PARTS, k=2)) + ".py"
        if candidate not in used_names:
            used_names.add(candidate)
            return candidate


def assign_variant_plans(*, instance_id: str, candidates: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    used_by_dir: dict[str, set[str]] = {}
    for candidate in candidates:
        runtime_real_file = Path(candidate["runtime_real_file"])
        wrapper_init_path = candidate["wrapper_init_path"]
        used_names = used_by_dir.setdefault(str(runtime_real_file.parent), set())
        used_names.add(runtime_real_file.name)
        used_names.update(Path(path).name for path in candidate.get("fake_file_paths", []))
        used_names.add(Path(wrapper_init_path).parent.name)

        real_name = _draw_name(_local_rng(seed, instance_id, wrapper_init_path, "real"), used_names)
        variant_rng = _local_rng(seed, instance_id, wrapper_init_path, "variants")
        variant_names = [_draw_name(variant_rng, used_names) for _ in range(4)]
        transforms = [
            ("invert_if_conditions", variant_names[0]),
            ("shuffle_proxy_imports", variant_names[1]),
            ("shuffle_dependency_keys", variant_names[2]),
            ("add_unused_function", variant_names[3]),
        ]

        plans.append(
            {
                **candidate,
                "original_hidden_impl_name": candidate["hidden_impl_name"],
                "original_runtime_real_file": candidate["runtime_real_file"],
                "hidden_impl_name": real_name,
                "runtime_real_file": str(runtime_real_file.with_name(real_name)),
                "variant_specs": [
                    {
                        "transform": transform_name,
                        "filename": filename,
                        "path": str(runtime_real_file.with_name(filename)),
                        "seed": int(
                            hashlib.sha1(
                                f"{seed}:{instance_id}:{wrapper_init_path}:{transform_name}".encode("utf-8")
                            ).hexdigest()[:12],
                            16,
                        ),
                    }
                    for transform_name, filename in transforms
                ],
            }
        )
    return plans


def build_injection_script(*, plans: list[dict[str, Any]], placeholder: str) -> str:
    payload = json.dumps(plans, ensure_ascii=False, indent=2)
    return f"""import ast
import io
import json
import random
import tokenize
from pathlib import Path

try:
    import libcst as cst
    from libcst.metadata import PositionProvider
except Exception:
    cst = None
    PositionProvider = None

PLACEHOLDER = {placeholder!r}
PLANS = {payload}
HAS_CST = cst is not None and PositionProvider is not None


def compute_offsets(source):
    offsets = [0]
    total = 0
    for line in source.splitlines(True):
        total += len(line)
        offsets.append(total)
    return offsets


def lc_to_offset(offsets, line, col):
    return offsets[line - 1] + col


def node_offsets(source, node, offsets):
    start = lc_to_offset(offsets, node.lineno, node.col_offset)
    end_lineno = getattr(node, "end_lineno", None)
    end_col_offset = getattr(node, "end_col_offset", None)
    if end_lineno is not None and end_col_offset is not None:
        return start, lc_to_offset(offsets, end_lineno, end_col_offset)
    line_end = source.find("\\n", start)
    return start, len(source) if line_end == -1 else line_end


def unwrap_subscript_slice(node):
    slice_node = node.slice
    if hasattr(ast, "Index") and isinstance(slice_node, ast.Index):
        return slice_node.value
    return slice_node


def flatten_single_char_concat(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) == 1:
        return [node.value]
    if hasattr(ast, "Str") and isinstance(node, ast.Str) and len(node.s) == 1:
        return [node.s]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = flatten_single_char_concat(node.left)
        right = flatten_single_char_concat(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def apply_edits(source, edits):
    updated = source
    for start, end, replacement in sorted(edits, key=lambda item: item[0], reverse=True):
        updated = updated[:start] + replacement + updated[end:]
    return updated


def strip_comments_and_docstrings(source):
    tokens = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type != tokenize.COMMENT:
            tokens.append(tok)
    updated = tokenize.untokenize(tokens)
    if isinstance(updated, bytes):
        updated = updated.decode("utf-8")
    if not updated.endswith("\\n"):
        updated += "\\n"

    tree = ast.parse(updated)
    offsets = compute_offsets(updated)
    edits = []
    docstring_nodes = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    for node in ast.walk(tree):
        if not isinstance(node, docstring_nodes):
            continue
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if not isinstance(first, ast.Expr):
            continue
        value = getattr(first, "value", None)
        is_string = (
            isinstance(value, ast.Constant) and isinstance(value.value, str)
        ) or (
            hasattr(ast, "Str") and isinstance(value, ast.Str)
        )
        if not is_string:
            continue
        start, end = node_offsets(updated, first, offsets)
        edits.append((start, end, ""))

    updated = apply_edits(updated, edits)
    updated = "# abandon file\\n" + updated.lstrip("\\n")
    return updated if updated.endswith("\\n") else updated + "\\n"


def fallback_delete_ten_lines(source, seed):
    lines = source.splitlines(True)
    candidates = [index for index, line in enumerate(lines) if line.strip() and not line.lstrip().startswith("#")]
    if not candidates:
        return source, {{"mutation_count": 0, "fallback": True, "applied_transform": "delete_lines"}}
    rng = random.Random(seed)
    rng.shuffle(candidates)
    for delete_count in range(min(10, len(candidates)), 0, -1):
        removed = set(candidates[:delete_count])
        updated = "".join(line for index, line in enumerate(lines) if index not in removed)
        if not updated.strip():
            continue
        if not updated.endswith("\\n"):
            updated += "\\n"
        try:
            ast.parse(updated)
            return updated, {{"mutation_count": delete_count, "fallback": True, "applied_transform": "delete_lines"}}
        except Exception:
            pass
    return source, {{"mutation_count": 0, "fallback": True, "applied_transform": "delete_lines"}}


if HAS_CST:
    class IfCollector(cst.CSTVisitor):
        METADATA_DEPENDENCIES = (PositionProvider,)

        def __init__(self):
            self.records = []

        def visit_If(self, node):
            position = self.get_metadata(PositionProvider, node.test, None)
            if position is not None:
                self.records.append((position.start.line, position.start.column, position.end.line, position.end.column))


    class IfInvertTransformer(cst.CSTTransformer):
        METADATA_DEPENDENCIES = (PositionProvider,)

        def __init__(self, selected_records):
            self.selected_records = set(selected_records)
            self.mutation_count = 0

        def leave_If(self, original_node, updated_node):
            position = self.get_metadata(PositionProvider, original_node.test, None)
            if position is None:
                return updated_node
            record = (position.start.line, position.start.column, position.end.line, position.end.column)
            if record not in self.selected_records:
                return updated_node
            self.mutation_count += 1
            test = updated_node.test
            if isinstance(test, cst.UnaryOperation) and isinstance(test.operator, cst.Not):
                return updated_node.with_changes(test=test.expression)
            return updated_node.with_changes(test=cst.UnaryOperation(operator=cst.Not(), expression=test))


def transform_invert_if_conditions(source, seed):
    if HAS_CST:
        module = cst.parse_module(source)
        wrapper = cst.metadata.MetadataWrapper(module)
        collector = IfCollector()
        wrapper.visit(collector)
        if collector.records:
            rng = random.Random(seed)
            chosen = rng.sample(collector.records, max(1, len(collector.records) // 2))
            transformer = IfInvertTransformer(chosen)
            updated = wrapper.visit(transformer).code
            if transformer.mutation_count > 0:
                try:
                    ast.parse(updated)
                    return updated, {{"mutation_count": transformer.mutation_count, "fallback": False, "applied_transform": "invert_if_conditions"}}
                except Exception:
                    pass

    tree = ast.parse(source)
    offsets = compute_offsets(source)
    candidates = [node.test for node in ast.walk(tree) if isinstance(node, ast.If)]
    if not candidates:
        return fallback_delete_ten_lines(source, seed)
    rng = random.Random(seed)
    chosen = rng.sample(candidates, max(1, len(candidates) // 2))
    edits = []
    for test_node in chosen:
        start, end = node_offsets(source, test_node, offsets)
        if isinstance(test_node, ast.UnaryOp) and isinstance(test_node.op, ast.Not):
            inner_start, inner_end = node_offsets(source, test_node.operand, offsets)
            replacement = source[inner_start:inner_end] or source[start:end]
        else:
            replacement = "not (" + source[start:end] + ")"
        edits.append((start, end, replacement))
    updated = apply_edits(source, edits)
    try:
        ast.parse(updated)
        return updated, {{"mutation_count": len(edits), "fallback": False, "applied_transform": "invert_if_conditions"}}
    except Exception:
        return fallback_delete_ten_lines(source, seed)


def transform_shuffle_proxy_imports(source, seed):
    tree = ast.parse(source)
    offsets = compute_offsets(source)
    alias_edits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module is None:
            continue
        if not node.module.startswith("proxy_"):
            continue
        if len(node.names) != 1:
            continue
        alias = node.names[0]
        if not isinstance(alias, ast.alias) or not alias.asname:
            continue
        start = source.find(alias.asname, lc_to_offset(offsets, node.lineno, node.col_offset))
        if start == -1:
            continue
        alias_edits.append((start, start + len(alias.asname), alias.asname))
    if len(alias_edits) < 2:
        return fallback_delete_ten_lines(source, seed)
    rng = random.Random(seed)
    aliases_before = [item[2] for item in alias_edits]
    aliases_after = list(aliases_before)
    rng.shuffle(aliases_after)
    if aliases_after == aliases_before:
        aliases_after = aliases_after[1:] + aliases_after[:1]
    updated = apply_edits(
        source,
        [(start, end, new_alias) for (start, end, _old_alias), new_alias in zip(alias_edits, aliases_after)],
    )
    try:
        ast.parse(updated)
        return updated, {{"mutation_count": len(alias_edits), "fallback": False, "applied_transform": "shuffle_proxy_imports"}}
    except Exception:
        return fallback_delete_ten_lines(source, seed)


def transform_shuffle_dependency_keys(source, seed):
    tree = ast.parse(source)
    offsets = compute_offsets(source)
    groups = {{}}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Subscript):
            continue
        if not isinstance(node.value, ast.Name) or not node.value.id.startswith("dependencies_"):
            continue
        key_node = unwrap_subscript_slice(node)
        key_chars = flatten_single_char_concat(key_node)
        if key_chars is None or len(key_chars) < 2:
            continue
        start, end = node_offsets(source, key_node, offsets)
        groups.setdefault(node.value.id, []).append(
            {{
                "start": start,
                "end": end,
                "expr": source[start:end],
                "key": "".join(key_chars),
            }}
        )
    eligible = [items for items in groups.values() if len(items) >= 2]
    if not eligible:
        return fallback_delete_ten_lines(source, seed)
    target = max(eligible, key=len)
    exprs_before = [item["expr"] for item in target]
    exprs_after = list(exprs_before)
    rng = random.Random(seed)
    rng.shuffle(exprs_after)
    if exprs_after == exprs_before:
        exprs_after = exprs_after[1:] + exprs_after[:1]
    updated = apply_edits(
        source,
        [
            (item["start"], item["end"], new_expr)
            for item, new_expr in zip(target, exprs_after)
        ],
    )
    try:
        ast.parse(updated)
        return updated, {{"mutation_count": len(target), "fallback": False, "applied_transform": "shuffle_dependency_keys"}}
    except Exception:
        return fallback_delete_ten_lines(source, seed)


def transform_add_unused_function(source, seed):
    func_name = "general_released"
    if func_name in source:
        func_name = "general_released_%d" % (seed % 1000)
    suffix = "\\n"
    if "if __name__ == \\"__main__\\":" in source:
        marker = source.index('if __name__ == "__main__":')
        insertion = (
            "\\n\\n"
            "def %s(records, keep_empty=False):\\n"
            "    bucket = {{}}\\n"
            "    for key, value in records:\\n"
            "        if value or keep_empty:\\n"
            "            bucket[str(key)] = value\\n"
            "    return bucket\\n"
        ) % func_name
        updated = source[:marker].rstrip("\\n") + insertion + "\\n\\n" + source[marker:]
    else:
        updated = source.rstrip("\\n") + (
            "\\n\\n"
            "def %s(records, keep_empty=False):\\n"
            "    bucket = {{}}\\n"
            "    for key, value in records:\\n"
            "        if value or keep_empty:\\n"
            "            bucket[str(key)] = value\\n"
            "    return bucket\\n"
        ) % func_name + suffix
    try:
        ast.parse(updated)
        return updated, {{"mutation_count": 1, "fallback": False, "applied_transform": "add_unused_function", "function_name": func_name}}
    except Exception:
        return fallback_delete_ten_lines(source, seed)


TRANSFORMS = {{
    "invert_if_conditions": transform_invert_if_conditions,
    "shuffle_proxy_imports": transform_shuffle_proxy_imports,
    "shuffle_dependency_keys": transform_shuffle_dependency_keys,
    "add_unused_function": transform_add_unused_function,
}}


results = []
for plan in PLANS:
    wrapper_path = Path(plan["wrapper_init_path"])
    original_real_path = Path(plan.get("original_runtime_real_file") or plan["runtime_real_file"])
    real_path = Path(plan["runtime_real_file"])
    wrapper_text = wrapper_path.read_text(encoding="utf-8")
    original_hidden_impl_name = plan.get("original_hidden_impl_name") or plan["hidden_impl_name"]
    if original_hidden_impl_name not in wrapper_text:
        raise ValueError("Missing hidden impl marker %s in %s" % (original_hidden_impl_name, wrapper_path))
    wrapper_path.write_text(wrapper_text.replace(original_hidden_impl_name, PLACEHOLDER), encoding="utf-8")

    removed_fake_paths = []
    for fake_path_str in plan.get("fake_file_paths", []):
        fake_path = Path(fake_path_str)
        if fake_path.exists():
            fake_path.unlink()
            removed_fake_paths.append(str(fake_path))

    clean_source = strip_comments_and_docstrings(original_real_path.read_text(encoding="utf-8"))
    if original_real_path != real_path:
        if real_path.exists():
            raise FileExistsError("Injected real file path already exists: %s" % real_path)
        original_real_path.rename(real_path)
    real_path.write_text(clean_source, encoding="utf-8")

    generated_variants = []
    for variant in plan["variant_specs"]:
        new_source, meta = TRANSFORMS[variant["transform"]](clean_source, variant["seed"])
        ast.parse(new_source)
        variant_path = Path(variant["path"])
        if variant_path.exists():
            raise FileExistsError("Variant path already exists: %s" % variant_path)
        variant_path.write_text(new_source, encoding="utf-8")
        generated_variants.append(
            {{
                "transform": variant["transform"],
                "path": str(variant_path),
                "filename": variant["filename"],
                **meta,
            }}
        )

    results.append(
        {{
            "wrapper_init_path": str(wrapper_path),
            "original_runtime_real_file": str(original_real_path),
            "runtime_real_file": str(real_path),
            "placeholder": PLACEHOLDER,
            "removed_fake_paths": removed_fake_paths,
            "generated_variants": generated_variants,
        }}
    )

print(json.dumps({{"ok": True, "updated": len(results), "results": results}}, ensure_ascii=False))
"""


def run_python_in_container(container: docker.models.containers.Container, script: str) -> tuple[bool, str]:
    result = container.exec_run(["python3", "-c", script], user="root", workdir="/testbed")
    return result.exit_code == 0, result.output.decode("utf-8", errors="ignore")


def apply_instance_injection(
    client: docker.DockerClient,
    *,
    instance_id: str,
    metadata_path: Path,
    source_tag: str,
    target_tag: str,
    placeholder: str,
    seed: int,
    overwrite: bool,
    git_user_name: str,
    git_user_email: str,
    commit_message: str,
) -> dict[str, Any]:
    candidates = collect_wrapper_candidates(load_json(metadata_path))
    if not candidates:
        return {"instance_id": instance_id, "status": "skipped_no_wrapper_candidates", "metadata_path": str(metadata_path)}

    plans = assign_variant_plans(instance_id=instance_id, candidates=candidates, seed=seed)
    repo = instance_id_to_repo(instance_id)
    source_image = f"{repo}:{source_tag}"
    target_image = f"{repo}:{target_tag}"

    if not overwrite:
        try:
            client.images.get(target_image)
            return {
                "instance_id": instance_id,
                "status": "skipped_target_exists",
                "candidate_count": len(plans),
                "plans": plans,
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
        ok, output = run_python_in_container(container, build_injection_script(plans=plans, placeholder=placeholder))
        if not ok:
            raise RuntimeError(f"wrapper/variant injection failed: {output}")

        container.exec_run(f"git config --global user.email {shlex.quote(git_user_email)}")
        container.exec_run(f"git config --global user.name {shlex.quote(git_user_name)}")
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
        try:
            parsed_output = json.loads(output.strip().splitlines()[-1])
        except Exception:
            parsed_output = {"raw_output": output}
        return {
            "instance_id": instance_id,
            "status": "ok",
            "candidate_count": len(plans),
            "plans": plans,
            "injection_result": parsed_output,
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
    parser = argparse.ArgumentParser(description="Compact wrapper placeholder injector with three fake-file transforms.")
    parser.add_argument("--instances-json", default=DEFAULT_INSTANCES_JSON)
    parser.add_argument("--metadata-dir", default=DEFAULT_METADATA_DIR)
    parser.add_argument("--source-tag", default=DEFAULT_SOURCE_TAG)
    parser.add_argument("--target-tag", default=DEFAULT_TARGET_TAG)
    parser.add_argument("--summary-path", default=DEFAULT_SUMMARY_PATH)
    parser.add_argument("--placeholder", default=DEFAULT_PLACEHOLDER)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--stop-on-error", action="store_true")
    parser.add_argument("--git-user-name", default=DEFAULT_GIT_USER_NAME)
    parser.add_argument("--git-user-email", default=DEFAULT_GIT_USER_EMAIL)
    parser.add_argument("--commit-message", default=DEFAULT_COMMIT_MESSAGE)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    metadata_dir = Path(args.metadata_dir)
    if docker is None:
        raise RuntimeError("Missing Python package 'docker'. Install it first, for example: pip install docker")
    if not Path(args.instances_json).exists():
        raise FileNotFoundError(f"Instances JSON not found: {args.instances_json}")
    if not metadata_dir.exists():
        raise FileNotFoundError(f"Metadata directory not found: {metadata_dir}")

    client = docker.from_env()
    results: list[dict[str, Any]] = []
    for instance_id in normalize_instance_ids(load_json(args.instances_json)):
        metadata_path = metadata_dir / f"{instance_id}.json"
        if not metadata_path.exists():
            result = {"instance_id": instance_id, "status": "missing_metadata", "metadata_path": str(metadata_path)}
        else:
            try:
                result = apply_instance_injection(
                    client,
                    instance_id=instance_id,
                    metadata_path=metadata_path,
                    source_tag=args.source_tag,
                    target_tag=args.target_tag,
                    placeholder=args.placeholder,
                    seed=args.seed,
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
                    "traceback": traceback.format_exc(),
                    "metadata_path": str(metadata_path),
                }
                print(f"[ERROR] {instance_id}")
                print(result["traceback"])
                if args.stop_on_error:
                    results.append(result)
                    raise
        results.append(result)
        print(json.dumps({"instance_id": instance_id, "status": result.get("status")}, ensure_ascii=False))

    summary = {
        "instances_json": args.instances_json,
        "metadata_dir": str(metadata_dir),
        "source_tag": args.source_tag,
        "target_tag": args.target_tag,
        "placeholder": args.placeholder,
        "seed": args.seed,
        "git_user_name": args.git_user_name,
        "git_user_email": args.git_user_email,
        "commit_message": args.commit_message,
        "results": results,
    }
    Path(args.summary_path).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved summary to: {args.summary_path}")


if __name__ == "__main__":
    main()
