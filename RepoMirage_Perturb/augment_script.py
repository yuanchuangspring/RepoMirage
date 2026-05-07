#!/usr/bin/env python3
# -*- coding: utf-8 -*-

AUGMENT_SCRIPT = r"""
import os
import sys
import ast
import json
import uuid
import shutil
import random
import string
import hashlib
import libcst as cst
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import List, Dict, Any, Union, Tuple, Sequence, Optional, Set

from libcst.metadata import PositionProvider, QualifiedNameProvider, QualifiedNameSource

# ----------------- Configuration -----------------

CONFIG_FILENAME = "dependencies.json"
CONFIG_FILENAME_PREFIX = "dependencies"
GLOBAL_CONF_VAR = "dependencies_123"
METADATA_VERSION = "1.0"
FAKE_FILE_NAME = "target_instruction.py"
REAL_FILE_NAME = "normal_code.py"
PERTURBATION_TYPES = (
    "dynamic_dependency",
    "proxy_import",
    "fake_files",
    "in_place_hiding",
)

# ----------------- Utilities -----------------

def rand_str(k=4):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=k))

def rand_var_name():
    return f"_lll_{rand_str(4)}"

def rand_file_stem(min_parts=2, max_parts=3):
    vocab = [
        "alpha", "delta", "matrix", "orchid", "vector", "lumen", "cinder", "opal",
        "flux", "harbor", "echo", "quartz", "willow", "kappa", "ember", "tundra",
        "glyph", "marble", "spruce", "atlas", "nova", "cobalt", "ripple", "fable",
        "zenith", "canyon", "pollen", "cedar", "aurora", "signal", "meadow", "drift",
    ]
    pieces = random.sample(vocab, k=random.randint(min_parts, max_parts))
    if random.random() < 0.7:
        pieces.append(rand_str(random.randint(2, 5)))
    return "_".join(pieces)

def read_text(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

def write_text(path, s):
    # print(f"[Write] {path}")
    with open(path, 'w', encoding='utf-8') as f:
        f.write(s)

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

def load_json_or_empty(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

def normalize_enabled_perturbations(raw):
    if not raw:
        return set(PERTURBATION_TYPES)

    if isinstance(raw, str):
        raw_items = [raw]
    else:
        raw_items = list(raw)

    enabled = []
    for item in raw_items:
        if item in PERTURBATION_TYPES and item not in enabled:
            enabled.append(item)
    return set(enabled) if enabled else set(PERTURBATION_TYPES)

def make_dead_code():
    fname = f"_in_use_{rand_str()}"
    return f'''
def {fname}():
    data = []
    for i in range(5):
        data.append(i * 2)
    return sum(data)    
'''

def iso_utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()

def normalize_relpath(path: str, repo_root: str) -> str:
    abs_path = os.path.abspath(path)
    root = os.path.abspath(repo_root)
    if abs_path == root:
        return "."
    if abs_path.startswith(root + os.sep):
        return os.path.relpath(abs_path, root)
    return path

def module_name_from_path(path: str, repo_root: str) -> Optional[str]:
    rel_path = normalize_relpath(path, repo_root)
    if rel_path.startswith(".."):
        return None
    rel_no_ext, ext = os.path.splitext(rel_path)
    if ext != ".py":
        return None
    if os.path.basename(rel_path) == "__init__.py":
        rel_no_ext = os.path.dirname(rel_path)
    parts = [part for part in rel_no_ext.split(os.sep) if part and part != "."]
    return ".".join(parts) if parts else None

def is_dependency_json_name(filename: str) -> bool:
    if filename == CONFIG_FILENAME:
        return True
    return filename.startswith(f"{CONFIG_FILENAME_PREFIX}_") and filename.endswith(".json")

def list_dependency_json_paths(dirname: str) -> List[str]:
    try:
        names = os.listdir(dirname)
    except Exception:
        return []
    return sorted(
        os.path.join(dirname, name)
        for name in names
        if is_dependency_json_name(name)
    )

def choose_dependency_json_paths(dirname: str, count: int) -> List[str]:
    if count <= 0:
        return []
    file_count = 1 if count < 3 else max(2, (count + 2) // 3)
    chosen: List[str] = []
    existing = list_dependency_json_paths(dirname)
    available_existing = existing[:]

    if file_count == 1:
        if os.path.join(dirname, CONFIG_FILENAME) in existing:
            return [os.path.join(dirname, CONFIG_FILENAME)]
        if available_existing:
            return [random.choice(available_existing)]
        return [os.path.join(dirname, CONFIG_FILENAME)]

    while len(chosen) < file_count and available_existing:
        path = available_existing.pop(random.randrange(len(available_existing)))
        if path not in chosen:
            chosen.append(path)

    used_names = {os.path.basename(path) for path in existing + chosen}
    while len(chosen) < file_count:
        candidate = f"{CONFIG_FILENAME_PREFIX}_{rand_file_stem(1, 3)}_{rand_str(4)}.json"
        if candidate in used_names:
            continue
        used_names.add(candidate)
        chosen.append(os.path.join(dirname, candidate))
    return chosen

@dataclass
class SourceLocation:
    start_line: int
    start_column: int
    end_line: int
    end_column: int

@dataclass
class DynamicConstantRecord:
    constant_name: Optional[str]
    literal_type: str
    original_value: Any
    json_path: str
    json_key: str
    source_code_location: Optional[SourceLocation]
    replacement_expression: str
    rewritten_access_pattern: str
    runtime_value_source: str

@dataclass
class ProxyMappingRecord:
    original_import: str
    rewritten_import: str
    original_dependency: str
    proxy_module: str
    proxy_file_path: str
    runtime_real_target: str
    affected_symbols: Dict[str, Optional[str]]
    proxy_chain: List[str] = field(default_factory=list)
    proxy_depth: int = 1
    bundle_members: List[str] = field(default_factory=list)
    middle_layer_candidates: List[str] = field(default_factory=list)

@dataclass
class FakeFileRecord:
    fake_file_path: str
    fake_name: str
    drop_rate: float
    dropped_functions: List[str] = field(default_factory=list)

@dataclass
class PerturbationNamingPlan:
    fake_file_name: str = FAKE_FILE_NAME
    real_file_name: str = REAL_FILE_NAME

@dataclass
class InPlaceHidingRecord:
    original_file_path: str
    hidden_real_file_path: str
    wrapper_package_path: str
    wrapper_init_path: str
    wrapper_import_relation: Dict[str, Any]
    public_module_entry: Optional[str]
    runtime_real_file: str

@dataclass
class FilePerturbationRecord:
    original_file_path: str
    relative_file_path: str
    file_language: str
    extension: str
    was_perturbed: bool
    perturbation_types: List[str]
    source_reason: str
    runtime_real_file: str
    semantic_anchor_files: List[str] = field(default_factory=list)
    distractor_files: List[str] = field(default_factory=list)
    perturbations: Dict[str, Any] = field(default_factory=dict)

class RepoMirageMetadataCollector:
    def __init__(self, sample_context: Dict[str, Any]):
        self.sample_context = sample_context
        self.proxy_count = 0
        self.extracted_constant_count = 0
        self.file_records: List[FilePerturbationRecord] = []
        self.path_resolution_map: List[Dict[str, Any]] = []

    def add_file_stats(self, proxy_count: int, extracted_constant_count: int) -> None:
        self.proxy_count += proxy_count
        self.extracted_constant_count += extracted_constant_count

    def add_file_record(self, record: FilePerturbationRecord) -> None:
        self.file_records.append(record)

    def add_resolution(self, entry: Dict[str, Any]) -> None:
        self.path_resolution_map.append(entry)

    def build(self) -> Dict[str, Any]:
        patch_text = self.sample_context.get("patch_text", "")
        patch_touched_files = self.sample_context.get("patch_touched_files", [])
        repo_path = self.sample_context.get("repo_path")
        return {
            "metadata_version": METADATA_VERSION,
            "generation_time": iso_utc_now(),
            "sample": {
                "instance_id": self.sample_context.get("instance_id"),
                "sample_id": self.sample_context.get("sample_id") or self.sample_context.get("instance_id"),
                "repo_name": self.sample_context.get("repo_name"),
                "repo_path": repo_path,
                "clean_repo_path": self.sample_context.get("clean_repo_path"),
                "mirage_repo_path": self.sample_context.get("mirage_repo_path", repo_path),
                "gold_patch_path": self.sample_context.get("gold_patch_path"),
                "patch_identity": {
                    "source": self.sample_context.get("patch_source", "instance.patch"),
                    "sha1": self.sample_context.get("patch_sha1") or sha1_text(patch_text),
                    "touched_files": patch_touched_files,
                },
                "patch_touched_files": patch_touched_files,
            },
            "proxy_count": self.proxy_count,
            "extracted_constant_count": self.extracted_constant_count,
            "files": [asdict(record) for record in self.file_records],
            "semantic_index": {
                "path_resolution_map": self.path_resolution_map,
            },
        }

# ----------------- Transformers -----------------

class ShadowDecoyTransformer(cst.CSTTransformer):
    def __init__(self, drop_rate=0.3):
        self.drop_rate = drop_rate
        self.dropped_functions: List[str] = []

    def leave_FunctionDef(self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef) -> Union[cst.FunctionDef, cst.RemovalSentinel]:
        if random.random() < self.drop_rate:
            self.dropped_functions.append(original_node.name.value)
            return cst.RemoveFromParent()
        return updated_node

def dependency_key_from_subscript(node: cst.Subscript) -> Optional[str]:
    if not isinstance(node.value, cst.Name) or node.value.value != GLOBAL_CONF_VAR:
        return None
    if len(node.slice) != 1:
        return None
    element = node.slice[0]
    if not isinstance(element.slice, cst.Index):
        return None
    value = element.slice.value
    if not isinstance(value, cst.SimpleString):
        return None
    try:
        key = ast.literal_eval(value.value)
    except Exception:
        return None
    return key if isinstance(key, str) else None

def split_string_parts(value: str) -> List[str]:
    return [value]

def render_split_string_expression(value: str) -> str:
    pieces = split_string_parts(value)
    return " + ".join(repr(piece) for piece in pieces)

def split_string_expression(value: str) -> cst.BaseExpression:
    pieces = split_string_parts(value)
    if len(pieces) <= 1:
        return cst.SimpleString(value=repr(value))

    expr: cst.BaseExpression = cst.SimpleString(value=repr(pieces[0]))
    for piece in pieces[1:]:
        expr = cst.BinaryOperation(
            left=expr,
            operator=cst.Add(),
            right=cst.SimpleString(value=repr(piece)),
        )
    return expr

def split_key_expression(key: str) -> cst.BaseExpression:
    if key == "":
        return cst.SimpleString(value=repr(key))

    pieces = list(key)
    expr: cst.BaseExpression = cst.SimpleString(value=repr(pieces[0]))
    for piece in pieces[1:]:
        expr = cst.BinaryOperation(
            left=expr,
            operator=cst.Add(),
            right=cst.SimpleString(value=repr(piece)),
        )
    return expr

def is_proxy_import_module(module_name: str) -> bool:
    return module_name.startswith("proxy_")

def extract_proxy_import_binding(node: cst.ImportFrom) -> Optional[Dict[str, str]]:
    if not isinstance(node.module, cst.Name):
        return None
    if not is_proxy_import_module(node.module.value):
        return None
    if isinstance(node.names, cst.ImportStar) or len(node.names) != 1:
        return None

    alias = node.names[0]
    if not isinstance(alias, cst.ImportAlias):
        return None
    if not isinstance(alias.name, cst.Name):
        return None
    if alias.asname is None or not isinstance(alias.asname.name, cst.Name):
        return None

    return {
        "module": node.module.value,
        "export_name": alias.name.value,
        "local_alias": alias.asname.name.value,
    }

def proxy_binding_key(binding: Dict[str, str]) -> Tuple[str, str, str]:
    return (binding["module"], binding["export_name"], binding["local_alias"])

def proxy_loader_temp_name(local_alias: str) -> str:
    return f"_mod_{sha1_text(local_alias)[:8]}"

def make_proxy_loader_call(module_name: str, export_name: str) -> cst.Call:
    return cst.Call(
        func=cst.Name("__import__"),
        args=[
            cst.Arg(value=split_string_expression(module_name)),
            cst.Arg(value=cst.Call(func=cst.Name("globals"), args=[])),
            cst.Arg(value=cst.Call(func=cst.Name("locals"), args=[])),
            cst.Arg(
                value=cst.List(
                    elements=[cst.Element(value=split_string_expression(export_name))]
                )
            ),
            cst.Arg(value=cst.Integer("0")),
        ],
    )

def format_real_proxy_import_rewrite(module_name: str, export_name: str, local_alias: str) -> str:
    temp_name = proxy_loader_temp_name(local_alias)
    module_expr = render_split_string_expression(module_name)
    export_expr = render_split_string_expression(export_name)
    return (
        f"{temp_name} = __import__({module_expr}, globals(), locals(), [{export_expr}], 0)\n"
        f"{local_alias} = getattr({temp_name}, {export_expr})"
    )

def replace_dependency_key_index(node: cst.Subscript, key_expr: cst.BaseExpression) -> cst.Subscript:
    if len(node.slice) != 1:
        return node
    element = node.slice[0]
    if not isinstance(element.slice, cst.Index):
        return node
    return node.with_changes(
        slice=[
            element.with_changes(
                slice=element.slice.with_changes(value=key_expr)
            )
        ]
    )

def build_dependency_key_permutation(records: Sequence[DynamicConstantRecord]) -> Dict[str, str]:
    keys = unique_paths([record.json_key for record in records])
    if len(keys) < 2:
        return {}

    random.shuffle(keys)
    offset = random.randrange(1, len(keys))
    rotated = keys[offset:] + keys[:offset]
    return dict(zip(keys, rotated))

class DependencyKeyPermutationTransformer(cst.CSTTransformer):
    def __init__(self, key_map: Dict[str, str]):
        self.key_map = key_map

    def leave_Subscript(self, original_node: cst.Subscript, updated_node: cst.Subscript) -> cst.Subscript:
        key = dependency_key_from_subscript(updated_node)
        if key is None or key not in self.key_map:
            return updated_node
        return replace_dependency_key_index(
            updated_node,
            cst.SimpleString(value=repr(self.key_map[key])),
        )

class DependencyKeySplitTransformer(cst.CSTTransformer):
    def __init__(self, keys: Sequence[str]):
        self.keys = set(keys)

    def leave_Subscript(self, original_node: cst.Subscript, updated_node: cst.Subscript) -> cst.Subscript:
        key = dependency_key_from_subscript(updated_node)
        if key is None or key not in self.keys:
            return updated_node
        return replace_dependency_key_index(updated_node, split_key_expression(key))

class DependencyStringSplitTransformer(cst.CSTTransformer):
    def __init__(self, values: Sequence[str]):
        self.values = set(values)

    def leave_SimpleString(self, original_node: cst.SimpleString, updated_node: cst.SimpleString) -> cst.BaseExpression:
        try:
            value = ast.literal_eval(updated_node.value)
        except Exception:
            return updated_node
        if not isinstance(value, str) or value not in self.values:
            return updated_node
        return split_key_expression(value)

class ProxyImportBindingCollector(cst.CSTVisitor):
    def __init__(self) -> None:
        self.bindings: List[Dict[str, str]] = []

    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
        binding = extract_proxy_import_binding(node)
        if binding is not None:
            self.bindings.append(binding)

def build_fake_proxy_usage_scramble(bindings: Sequence[Dict[str, str]]) -> Dict[str, str]:
    ordered: List[Dict[str, str]] = []
    seen = set()
    for binding in bindings:
        key = proxy_binding_key(binding)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(binding)

    if len(ordered) < 2:
        return {}

    rotated_aliases = ordered[-1:] + ordered[:-1]

    alias_map = {}
    for idx, binding in enumerate(ordered):
        rotated_alias = rotated_aliases[idx]
        alias_map[binding["local_alias"]] = rotated_alias["local_alias"]

    return alias_map

class FakeProxyUsageScrambleTransformer(cst.CSTTransformer):
    METADATA_DEPENDENCIES = (QualifiedNameProvider,)

    def __init__(self, alias_map: Dict[str, str]):
        self.alias_map = alias_map

    def leave_Name(self, original_node: cst.Name, updated_node: cst.Name) -> cst.Name:
        old = original_node.value
        if old not in self.alias_map:
            return updated_node

        qnames = self.get_metadata(QualifiedNameProvider, original_node, set())
        if any(qn.source == QualifiedNameSource.IMPORT for qn in qnames):
            return updated_node.with_changes(value=self.alias_map[old])
        return updated_node

class RealProxyImportSplitTransformer(cst.CSTTransformer):
    def leave_SimpleStatementLine(
        self,
        original_node: cst.SimpleStatementLine,
        updated_node: cst.SimpleStatementLine,
    ) -> Union[cst.SimpleStatementLine, cst.FlattenSentinel[cst.BaseStatement]]:
        if len(updated_node.body) != 1:
            return updated_node

        stmt = updated_node.body[0]
        if not isinstance(stmt, cst.ImportFrom):
            return updated_node

        binding = extract_proxy_import_binding(stmt)
        if binding is None:
            return updated_node

        temp_name = proxy_loader_temp_name(binding["local_alias"])
        import_assign = cst.Assign(
            targets=[cst.AssignTarget(target=cst.Name(value=temp_name))],
            value=make_proxy_loader_call(binding["module"], binding["export_name"]),
        )
        alias_assign = cst.Assign(
            targets=[cst.AssignTarget(target=cst.Name(value=binding["local_alias"]))],
            value=cst.Call(
                func=cst.Name("getattr"),
                args=[
                    cst.Arg(value=cst.Name(value=temp_name)),
                    cst.Arg(value=split_string_expression(binding["export_name"])),
                ],
            ),
        )

        first_stmt = cst.SimpleStatementLine(
            body=[import_assign],
            leading_lines=updated_node.leading_lines,
        )
        second_stmt = cst.SimpleStatementLine(
            body=[alias_assign],
            trailing_whitespace=updated_node.trailing_whitespace,
        )
        return cst.FlattenSentinel([first_stmt, second_stmt])

class ConstantExtractorTransformer(cst.CSTTransformer):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, config_dir: str):
        self.config_dir = config_dir
        self.changed = False
        self.extracted_constants: List[DynamicConstantRecord] = []
        self.json_paths: List[str] = []
        self._pending_constants: List[Dict[str, Any]] = []

    def _replace_literal(
        self,
        original_node: Union[cst.Integer, cst.Float],
        value: Any,
        literal_type: str,
    ) -> cst.Subscript:
        key = str(uuid.uuid4())[:8]
        self.changed = True
        replacement_expression = f"{GLOBAL_CONF_VAR}['{key}']"
        position = self.get_metadata(PositionProvider, original_node, None)
        location = None
        if position is not None:
            location = SourceLocation(
                start_line=position.start.line,
                start_column=position.start.column,
                end_line=position.end.line,
                end_column=position.end.column,
            )
        self._pending_constants.append(
            {
                "constant_name": None,
                "literal_type": literal_type,
                "original_value": value,
                "json_key": key,
                "source_code_location": location,
                "replacement_expression": replacement_expression,
            }
        )
        new_node = cst.Subscript(
            value=cst.Name(value=GLOBAL_CONF_VAR),
            slice=[
                cst.SubscriptElement(
                    slice=cst.Index(
                        value=cst.SimpleString(value=f"'{key}'")
                    )
                )
            ]
        )
        return new_node

    def leave_Integer(self, original_node: cst.Integer, updated_node: cst.Integer) -> Union[cst.Integer, cst.Subscript]:
        if random.random() > 1.0:
            return updated_node
        
        # print("Mod Constant Int")
        val = int(original_node.value, 0)
        return self._replace_literal(original_node, val, "int")

    def leave_Float(self, original_node: cst.Float, updated_node: cst.Float) -> Union[cst.Float, cst.Subscript]:
        if random.random() > 1.0:
            return updated_node

        # print("Mod Constant Float")
        return self._replace_literal(original_node, float(original_node.value), "float")

    def finalize_json_layout(self) -> None:
        total = len(self._pending_constants)
        if total == 0:
            self.json_paths = []
            self.extracted_constants = []
            return

        selected_paths = choose_dependency_json_paths(self.config_dir, total)
        self.json_paths = selected_paths
        buckets: Dict[str, Dict[str, Any]] = {path: load_json_or_empty(path) for path in selected_paths}

        pending = list(self._pending_constants)
        random.shuffle(pending)
        for item in pending:
            path = random.choice(selected_paths)
            buckets[path][item["json_key"]] = item["original_value"]
            self.extracted_constants.append(
                DynamicConstantRecord(
                    constant_name=item["constant_name"],
                    literal_type=item["literal_type"],
                    original_value=item["original_value"],
                    json_path=path,
                    json_key=item["json_key"],
                    source_code_location=item["source_code_location"],
                    replacement_expression=item["replacement_expression"],
                    rewritten_access_pattern=f"{GLOBAL_CONF_VAR}['<json_key>']",
                    runtime_value_source=path,
                )
            )

        for path, data in buckets.items():
            save_json(path, data)

class ImportProxyTransformer(cst.CSTTransformer):
    METADATA_DEPENDENCIES = (QualifiedNameProvider,)

    class _ImportCollector(cst.CSTVisitor):
        def __init__(self) -> None:
            self.real_names: List[str] = []

        def visit_Import(self, node: cst.Import) -> None:
            if len(node.names) != 1:
                return
            alias_node = node.names[0]
            if isinstance(alias_node.name, cst.Name):
                self.real_names.append(alias_node.name.value)

    def __init__(self, current_dir: str, repo_root: str):
        self.current_dir = current_dir
        self.repo_root = repo_root

        self.generated_proxies: List[str] = []
        self.alias_map: Dict[str, str] = {}
        self.proxy_records: List[ProxyMappingRecord] = []
        self.proxy_nodes: List[Dict[str, Any]] = []

        self.bundle_real_names: List[str] = []
        self.bundle_built: bool = False
        self.bundle_graph: Dict[str, Any] = {}
        self.real_to_bundle_endpoint: Dict[str, Dict[str, Any]] = {}
        self.proxy_endpoint_cache: Dict[str, Dict[str, Any]] = {}

    # ------------------------------
    # collect imports in current file
    # ------------------------------

    def visit_Module(self, node: cst.Module) -> None:
        collector = self._ImportCollector()
        node.visit(collector)

        seen = set()
        ordered = []
        for name in collector.real_names:
            if name not in seen:
                seen.add(name)
                ordered.append(name)
        self.bundle_real_names = ordered

    # ------------------------------
    # proxy node helpers
    # ------------------------------

    def _new_proxy_node(self, layer: int) -> Dict[str, Any]:
        while True:
            proxy_filename = f"proxy_{rand_str(5)}"
            proxy_path = os.path.join(self.current_dir, f"{proxy_filename}.py")
            if not os.path.exists(proxy_path):
                break

        node = {
            "id": proxy_filename,
            "layer": layer,
            "filename": proxy_filename,
            "path": proxy_path,
            "module_name": module_name_from_path(proxy_path, self.repo_root) or proxy_filename,
            "exports": {},          # real_name -> alias exported in this node
            "import_lines": [],
            "downstream": [],
            "is_materialized": False,
            "is_hub": False,
        }
        self.proxy_nodes.append(node)
        self.generated_proxies.append(proxy_filename)
        return node

    def _flush_proxy_node(self, node: Dict[str, Any]) -> None:
        lines: List[str] = []
        seen = set()

        for line in node["import_lines"]:
            if line not in seen:
                seen.add(line)
                lines.append(line)

        exported_aliases = list(node["exports"].values())
        if exported_aliases:
            quoted = ", ".join(repr(x) for x in exported_aliases)
            lines.append(f"__all__ = [{quoted}]")

        body = "\n".join(lines).strip()
        proxy_code = f"{body}\n\n{make_dead_code()}\n"
        write_text(node["path"], proxy_code)
        node["is_materialized"] = True

    def _mark_hubs(self, nodes: List[Dict[str, Any]], ratio: float = 0.3) -> None:
        if not nodes:
            return
        hub_count = max(1, int(len(nodes) * ratio))
        for node in random.sample(nodes, k=min(hub_count, len(nodes))):
            node["is_hub"] = True

    def _weighted_sample_nodes(
        self,
        candidates: List[Dict[str, Any]],
        k_min: int = 2,
        k_max: int = 3,
    ) -> List[Dict[str, Any]]:
        if not candidates:
            return []

        k = min(len(candidates), random.randint(k_min, k_max))
        if len(candidates) <= k:
            return list(candidates)

        weighted = []
        for node in candidates:
            weight = 3 if node.get("is_hub") else 1
            weighted.extend([node] * weight)

        picked: List[Dict[str, Any]] = []
        used = set()
        random.shuffle(weighted)

        for node in weighted:
            if node["id"] in used:
                continue
            used.add(node["id"])
            picked.append(node)
            if len(picked) >= k:
                break

        if len(picked) < k:
            remain = [n for n in candidates if n["id"] not in used]
            random.shuffle(remain)
            picked.extend(remain[: k - len(picked)])

        return picked

    # ------------------------------
    # dependency attach helpers
    # ------------------------------

    def _attach_real_dependency(self, node: Dict[str, Any], real_name: str) -> None:
        if real_name in node["exports"]:
            return

        export_name = f"dep_{rand_str(6)}"
        node["import_lines"].append(f"import {real_name} as {export_name}")
        node["exports"][real_name] = export_name
        node["downstream"].append({"type": "real", "target": real_name})

    def _attach_proxy_dependency_for_real(
        self,
        node: Dict[str, Any],
        child: Dict[str, Any],
        real_name: str,
        side_only: bool = False,
    ) -> None:
        if real_name not in child["exports"]:
            raise ValueError(
                f"Child proxy {child['filename']} does not export {real_name}"
            )

        child_alias = child["exports"][real_name]
        local_alias = f"dep_{rand_str(6)}" if not side_only else f"dep_{rand_str(5)}"

        node["import_lines"].append(
            f"from {child['filename']} import {child_alias} as {local_alias}"
        )

        node["downstream"].append(
            {
                "type": "proxy",
                "target": child["filename"],
                "real_name": real_name,
                "side_only": side_only,
            }
        )

        if not side_only and real_name not in node["exports"]:
            node["exports"][real_name] = local_alias

    def _nodes_exporting_real(
        self,
        nodes: List[Dict[str, Any]],
        real_name: str,
    ) -> List[Dict[str, Any]]:
        return [n for n in nodes if real_name in n["exports"]]

    # ------------------------------
    # build shared 4-layer bundle graph
    # ------------------------------

    def _build_proxy_bundle_graph(self, real_names: List[str]) -> Dict[str, Any]:
        if not real_names:
            return {
                "bundle_members": [],
                "layer0": [],
                "layer1": [],
                "layer2": [],
                "layer3": [],
                "endpoint_by_real": {},
            }

        k = len(real_names)

        # Four layers:
        # L0 = k      (entry, one per real)
        # L1 = 2k     (shared middle-1)
        # L2 = 2k     (shared middle-2)
        # L3 = k      (leaf, one per real, directly imports real module)
        layer0 = [self._new_proxy_node(layer=0) for _ in range(k)]
        layer1 = [self._new_proxy_node(layer=1) for _ in range(2 * k)]
        layer2 = [self._new_proxy_node(layer=2) for _ in range(2 * k)]
        layer3 = [self._new_proxy_node(layer=3) for _ in range(k)]

        self._mark_hubs(layer1, ratio=0.35)
        self._mark_hubs(layer2, ratio=0.35)

        real_to_l0 = {real_names[i]: layer0[i] for i in range(k)}
        real_to_l3 = {real_names[i]: layer3[i] for i in range(k)}

        # L3 -> real
        for real_name in real_names:
            leaf = real_to_l3[real_name]
            self._attach_real_dependency(leaf, real_name)
            self._flush_proxy_node(leaf)

        # Ensure every real has at least one L2 node on the main shared layer.
        for idx, real_name in enumerate(real_names):
            self._attach_proxy_dependency_for_real(layer2[idx], real_to_l3[real_name], real_name, side_only=False)

        # L2: each node supports 1~3 real modules by importing from L3
        for node in layer2:
            support_count = min(k, random.randint(1, min(3, k)))
            supported_reals = random.sample(real_names, k=support_count)

            for real_name in supported_reals:
                leaf = real_to_l3[real_name]
                self._attach_proxy_dependency_for_real(node, leaf, real_name, side_only=False)

            self._flush_proxy_node(node)

        # Ensure every real has at least one L1 node on the main shared layer.
        for idx, real_name in enumerate(real_names):
            mid2_candidates = self._nodes_exporting_real(layer2, real_name)
            if mid2_candidates:
                chosen_mid2 = random.choice(mid2_candidates)
                self._attach_proxy_dependency_for_real(layer1[idx], chosen_mid2, real_name, side_only=False)

        # L1: each node supports 1~3 real modules by importing from L2
        for node in layer1:
            support_count = min(k, random.randint(1, min(3, k)))
            supported_reals = random.sample(real_names, k=support_count)

            for real_name in supported_reals:
                mid2_candidates = self._nodes_exporting_real(layer2, real_name)
                if not mid2_candidates:
                    continue
                chosen_mid2 = random.choice(mid2_candidates)
                self._attach_proxy_dependency_for_real(node, chosen_mid2, real_name, side_only=False)

            self._flush_proxy_node(node)

        # L0: one entry per real, choose two candidate middle nodes when possible
        endpoint_by_real: Dict[str, Dict[str, Any]] = {}

        for real_name in real_names:
            entry = real_to_l0[real_name]
            candidates = self._nodes_exporting_real(layer1, real_name)

            if not candidates:
                fallback_mid1 = layer1[real_names.index(real_name)]
                self._attach_proxy_dependency_for_real(entry, fallback_mid1, real_name, side_only=False)
            else:
                # Pick fixed middle-layer candidates; if fewer are available, use as many as possible.
                chosen = self._weighted_sample_nodes(
                    candidates,
                    k_min=min(2, len(candidates)),
                    k_max=min(2, len(candidates)),
                )
                if not chosen:
                    chosen = [random.choice(candidates)]

                main_child = random.choice(chosen)
                self._attach_proxy_dependency_for_real(entry, main_child, real_name, side_only=False)

                for child in chosen:
                    if child["id"] == main_child["id"]:
                        continue
                    self._attach_proxy_dependency_for_real(entry, child, real_name, side_only=True)

            self._flush_proxy_node(entry)

            # recover one main path: L0 -> L1 -> L2 -> L3
            chain = [entry["filename"]]
            current = entry
            visited = set()

            while True:
                if current["id"] in visited:
                    break
                visited.add(current["id"])

                proxy_targets = [
                    d for d in current["downstream"]
                    if d["type"] == "proxy" and d["real_name"] == real_name and not d["side_only"]
                ]
                if not proxy_targets:
                    break

                nxt_name = proxy_targets[0]["target"]
                chain.append(nxt_name)
                nxt = next((n for n in self.proxy_nodes if n["filename"] == nxt_name), None)
                if nxt is None:
                    break
                current = nxt

            # Only record middle-layer proxies used by the main chain (layer 1 or 2).
            # Do not write the entry layer (L0) or leaf layer (L3) to metadata.
            middle_candidates = []
            for proxy_name in chain[1:]:
                proxy_node = next(
                    (n for n in self.proxy_nodes if n["filename"] == proxy_name),
                    None,
                )
                if proxy_node is not None and proxy_node.get("layer") in (1, 2):
                    middle_candidates.append(proxy_name)

            endpoint_by_real[real_name] = {
                "module_name": entry["module_name"],
                "import_module": entry["filename"],
                "path": entry["path"],
                "export_name": entry["exports"][real_name],
                "bundle_members": list(real_names),
                "chain": chain,
                "middle_layer_candidates": middle_candidates,
            }

        return {
            "bundle_members": list(real_names),
            "layer0": [n["filename"] for n in layer0],
            "layer1": [n["filename"] for n in layer1],
            "layer2": [n["filename"] for n in layer2],
            "layer3": [n["filename"] for n in layer3],
            "endpoint_by_real": endpoint_by_real,
        }

    def _ensure_bundle_built(self) -> None:
        if self.bundle_built:
            return

        if not self.bundle_real_names:
            self.bundle_built = True
            self.bundle_graph = {
                "bundle_members": [],
                "layer0": [],
                "layer1": [],
                "layer2": [],
                "layer3": [],
                "endpoint_by_real": {},
            }
            return

        self.bundle_graph = self._build_proxy_bundle_graph(self.bundle_real_names)
        self.real_to_bundle_endpoint = self.bundle_graph["endpoint_by_real"]
        self.bundle_built = True

    def _allocate_proxy_endpoint(self, real_name: str) -> Dict[str, Any]:
        cached = self.proxy_endpoint_cache.get(real_name)
        if cached is not None:
            return cached

        self._ensure_bundle_built()

        endpoint = self.real_to_bundle_endpoint.get(real_name)
        if endpoint is None:
            raise ValueError(f"No bundle endpoint found for dependency: {real_name}")

        self.proxy_endpoint_cache[real_name] = endpoint
        return endpoint

    # ------------------------------
    # CST rewrite
    # ------------------------------

    def leave_Import(
        self, original_node: cst.Import, updated_node: cst.Import
    ) -> Union[cst.Import, cst.ImportFrom]:
        if len(updated_node.names) != 1:
            return updated_node

        alias_node = updated_node.names[0]
        if not isinstance(alias_node.name, cst.Name):
            return updated_node

        real_name = alias_node.name.value
        current_alias = alias_node.asname.name.value if alias_node.asname else real_name

        new_obfuscated_alias = rand_var_name()
        self.alias_map[current_alias] = new_obfuscated_alias

        try:
            endpoint = self._allocate_proxy_endpoint(real_name)
        except Exception:
            return updated_node

        rewritten_import = (
            f"from {endpoint['import_module']} import "
            f"{endpoint['export_name']} as {new_obfuscated_alias}"
        )

        new_node = cst.ImportFrom(
            module=cst.Name(value=endpoint["import_module"]),
            names=[
                cst.ImportAlias(
                    name=cst.Name(value=endpoint["export_name"]),
                    asname=cst.AsName(name=cst.Name(value=new_obfuscated_alias)),
                )
            ],
            relative=[],
        )

        self.proxy_records.append(
            ProxyMappingRecord(
                original_import=(
                    f"import {real_name}"
                    if current_alias == real_name
                    else f"import {real_name} as {current_alias}"
                ),
                rewritten_import=rewritten_import,
                original_dependency=real_name,
                proxy_module=endpoint["import_module"],
                proxy_file_path=endpoint["path"],
                runtime_real_target=real_name,
                affected_symbols={
                    "original_alias": current_alias,
                    "rewritten_alias": new_obfuscated_alias,
                },
                proxy_chain=endpoint["chain"],
                proxy_depth=len(endpoint["chain"]),
                bundle_members=endpoint["bundle_members"],
                middle_layer_candidates=endpoint.get("middle_layer_candidates", []),
            )
        )
        return new_node

    def leave_ImportFrom(
        self, original_node: cst.ImportFrom, updated_node: cst.ImportFrom
    ) -> cst.ImportFrom:
        if original_node.module is not None:
            return updated_node.with_changes(module=original_node.module)
        return updated_node

    def leave_Name(self, original_node: cst.Name, updated_node: cst.Name) -> cst.Name:
        old = original_node.value
        if old not in self.alias_map:
            return updated_node

        qnames = self.get_metadata(QualifiedNameProvider, original_node, set())
        if any(qn.source == QualifiedNameSource.IMPORT for qn in qnames):
            return updated_node.with_changes(value=self.alias_map[old])
        return updated_node

    def leave_Attribute(self, original_node: cst.Attribute, updated_node: cst.Attribute) -> cst.Attribute:
        return updated_node

    def leave_Arg(self, original_node: cst.Arg, updated_node: cst.Arg) -> cst.Arg:
        return updated_node

# ----------------- Flow control -----------------

def inject_header_code(tree: cst.Module) -> cst.Module:
    header_code = f'''
import sys
import os
import json

_dir = os.path.dirname(os.path.abspath(__file__))
if _dir not in sys.path:
    sys.path.append(_dir)

{GLOBAL_CONF_VAR} = {{}}
for _name in sorted(os.listdir(_dir)):
    if _name == '{CONFIG_FILENAME}' or (_name.startswith('{CONFIG_FILENAME_PREFIX}_') and _name.endswith('.json')):
        _c_path = os.path.join(_dir, _name)
        try:
            with open(_c_path, 'r', encoding='utf-8') as f:
                _loaded = json.load(f)
                if isinstance(_loaded, dict):
                    {GLOBAL_CONF_VAR}.update(_loaded)
        except:
            pass
'''
    header_module = cst.parse_module(header_code)
    body = list(tree.body)

    insert_at = 0

    # 1) Skip module docstring.
    if body:
        first = body[0]
        if (
            isinstance(first, cst.SimpleStatementLine)
            and len(first.body) == 1
            and isinstance(first.body[0], cst.Expr)
            and isinstance(first.body[0].value, cst.SimpleString)
        ):
            insert_at = 1

    # 2) Continue past consecutive from __future__ imports.
    while insert_at < len(body):
        stmt = body[insert_at]
        if (
            isinstance(stmt, cst.SimpleStatementLine)
            and len(stmt.body) == 1
            and isinstance(stmt.body[0], cst.ImportFrom)
            and isinstance(stmt.body[0].module, cst.Name)
            and stmt.body[0].module.value == "__future__"
        ):
            insert_at += 1
        else:
            break

    new_body = body[:insert_at] + list(header_module.body) + body[insert_at:]
    return tree.with_changes(body=new_body)

def generate_decoy(
    abs_path,
    tree,
    n=1,
    drop_rate=0.3,
    naming_plan: Optional[PerturbationNamingPlan] = None,
):
    dirname = os.path.dirname(abs_path)
    naming_plan = naming_plan or PerturbationNamingPlan()
    fake_name = naming_plan.fake_file_name
    fake_records: List[FakeFileRecord] = []

    if os.path.basename(abs_path) == fake_name:
        return {"whether_applied": False, "fake_file_records": fake_records}

    path = os.path.join(dirname, fake_name)
    if os.path.exists(path) and os.path.abspath(path) != os.path.abspath(abs_path):
        return {"whether_applied": False, "fake_file_records": fake_records}

    try:
        tf = ShadowDecoyTransformer(drop_rate=drop_rate)
        write_text(path, tree.visit(tf).code)
        fake_records.append(
            FakeFileRecord(
                fake_file_path=path,
                fake_name=os.path.basename(path),
                drop_rate=drop_rate,
                dropped_functions=list(tf.dropped_functions),
            )
        )
    except Exception:
        return {"whether_applied": False, "fake_file_records": fake_records}

    return {"whether_applied": bool(fake_records), "fake_file_records": fake_records}

def unique_paths(items: List[str]) -> List[str]:
    seen = set()
    output: List[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            output.append(item)
    return output


def choose_unique_python_filename(
    parent_dir: str,
    *,
    used_names: set[str],
    reserved_stems: set[str] | None = None,
) -> str:
    reserved_stems = reserved_stems or set()
    while True:
        candidate = f"{rand_file_stem()}.py"
        stem = os.path.splitext(candidate)[0]
        if candidate == "__init__.py":
            continue
        if stem in reserved_stems:
            continue
        if candidate in used_names:
            continue
        if os.path.exists(os.path.join(parent_dir, candidate)):
            continue
        return candidate


def build_naming_plans(target_files: List[str]) -> Dict[str, PerturbationNamingPlan]:
    by_dir: Dict[str, List[str]] = {}
    for path in target_files:
        by_dir.setdefault(os.path.dirname(path), []).append(path)

    plans: Dict[str, PerturbationNamingPlan] = {}
    for parent_dir, paths in by_dir.items():
        sorted_paths = sorted(set(paths))
        if len(sorted_paths) <= 1:
            for path in sorted_paths:
                plans[path] = PerturbationNamingPlan()
            continue

        used_names = set(os.listdir(parent_dir))
        reserved_stems = {os.path.splitext(os.path.basename(path))[0] for path in sorted_paths}
        reserved_stems.update({"__init__"})

        for path in sorted_paths:
            real_file_name = choose_unique_python_filename(
                parent_dir,
                used_names=used_names,
                reserved_stems=reserved_stems,
            )
            used_names.add(real_file_name)
            reserved_stems.add(os.path.splitext(real_file_name)[0])

            fake_file_name = choose_unique_python_filename(
                parent_dir,
                used_names=used_names,
                reserved_stems=reserved_stems,
            )
            used_names.add(fake_file_name)
            reserved_stems.add(os.path.splitext(fake_file_name)[0])

            plans[path] = PerturbationNamingPlan(
                fake_file_name=fake_file_name,
                real_file_name=real_file_name,
            )

    return plans


# ----------------- [NEW] Sibling Shadow Logic -----------------
def apply_sibling_shadow(
    target_file_path: str,
    repo_root: str,
    naming_plan: Optional[PerturbationNamingPlan] = None,
):

    target = os.path.abspath(target_file_path)
    parent_dir = os.path.dirname(target)
    filename = os.path.basename(target)
    module_name, ext = os.path.splitext(filename)

    if ext != ".py":
        return {"whether_applied": False}
    if filename == "__init__.py":
        return {"whether_applied": False}
    if not os.path.isfile(target):
        return {"whether_applied": False}

    new_package_dir = os.path.join(parent_dir, module_name)
    if os.path.exists(new_package_dir):
        print(f"[SKIP] Sibling shadow skipped, package dir already exists: {new_package_dir}")
        return {"whether_applied": False}

    naming_plan = naming_plan or PerturbationNamingPlan()
    hidden_impl_name = naming_plan.real_file_name
    hidden_impl_path = os.path.join(parent_dir, hidden_impl_name)

    print(f" -> Applying Sibling Shadow: {module_name}")

    moved = False
    created_dir = False
    created_init = False

    try:
        # 1. Rename the original file.
        shutil.move(target, hidden_impl_path)
        moved = True

        # 2. Create a package directory with the original module name.
        os.mkdir(new_package_dir)
        created_dir = True

        # 3. Generate the proxy __init__.py.
        init_path = os.path.join(new_package_dir, "__init__.py")

        content = f'''import os as _os
import sys as _sys
import importlib.util as _util

_pkg_name = __name__

_parent_pkg = _pkg_name.rsplit(".", 1)[0] if "." in _pkg_name else ""

_impl_path = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "{hidden_impl_name}")

_spec = _util.spec_from_file_location(_pkg_name, _impl_path)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Cannot create spec for shadow impl: {{_impl_path}}")

_module = _util.module_from_spec(_spec)

_module.__file__ = _impl_path
_module.__package__ = _parent_pkg

_sys.modules[_pkg_name] = _module

_spec.loader.exec_module(_module)

globals().update(_module.__dict__)

__shadow_impl_path__ = _impl_path

del _os, _sys, _util, _pkg_name, _parent_pkg, _impl_path, _spec, _module
'''
        write_text(init_path, content)
        created_init = True

        print(f"    Shadowed: {hidden_impl_name} <-> {module_name}/ (Spec Proxy)")
        return {
            "whether_applied": True,
            "record": InPlaceHidingRecord(
                original_file_path=target,
                hidden_real_file_path=hidden_impl_path,
                wrapper_package_path=new_package_dir,
                wrapper_init_path=init_path,
                wrapper_import_relation={
                    "mechanism": "importlib.spec_from_file_location",
                    "wrapper_module_name": module_name_from_path(init_path, repo_root),
                    "hidden_impl_name": hidden_impl_name,
                },
                public_module_entry=module_name_from_path(target, repo_root),
                runtime_real_file=hidden_impl_path,
            ),
        }

    except Exception as e:
        print(f"[ERR] Sibling Shadow failed: {e}")

        try:
            if created_init:
                init_path = os.path.join(new_package_dir, "__init__.py")
                if os.path.exists(init_path):
                    os.remove(init_path)
        except Exception:
            pass

        try:
            if created_dir and os.path.isdir(new_package_dir):
                shutil.rmtree(new_package_dir)
        except Exception:
            pass

        try:
            if moved and os.path.exists(hidden_impl_path) and not os.path.exists(target):
                shutil.move(hidden_impl_path, target)
        except Exception:
            pass

        return {"whether_applied": False}

# ----------------- Main flow -----------------

def build_file_record(
    abs_path: str,
    repo_root: str,
    const_tf: ConstantExtractorTransformer,
    proxy_transformer: ImportProxyTransformer,
    decoy_info: Dict[str, Any],
    hiding_info: Dict[str, Any],
) -> FilePerturbationRecord:
    perturbation_types: List[str] = []
    semantic_anchor_files: List[str] = []
    distractor_files: List[str] = []
    runtime_real_file = abs_path

    proxy_records = getattr(proxy_transformer, "proxy_records", [])
    fake_records = decoy_info.get("fake_file_records", [])
    hiding_record = hiding_info.get("record")

    perturbations = {
        "proxy_import": {
            "whether_applied": bool(proxy_records),
            "proxy_mappings": [asdict(record) for record in proxy_records],
            "created_proxy_files": unique_paths([record.proxy_file_path for record in proxy_records]),
        },
        "dynamic_dependency": {
            "whether_applied": bool(const_tf.extracted_constants),
            "json_path": const_tf.json_paths[0] if const_tf.json_paths else None,
            "json_paths": unique_paths(list(const_tf.json_paths)),
            "extracted_constants": [asdict(record) for record in const_tf.extracted_constants],
        },
        "in_place_hiding": {
            "whether_applied": bool(hiding_record),
        },
        "fake_files": {
            "whether_applied": bool(fake_records),
            "real_runtime_file": abs_path,
            "fake_file_paths": unique_paths([record.fake_file_path for record in fake_records]),
            "fake_file_generation_summary": [asdict(record) for record in fake_records],
            "dependency_key_permutation": decoy_info.get("dependency_key_permutation", {}),
            "proxy_usage_scramble": decoy_info.get("proxy_usage_scramble", {}),
            "activation_status": "never_used_at_runtime",
        },
    }

    if const_tf.extracted_constants:
        perturbation_types.append("dynamic_dependency")
        semantic_anchor_files.extend(const_tf.json_paths)

    if proxy_records:
        perturbation_types.append("proxy_import")
        distractor_files.extend(record.proxy_file_path for record in proxy_records)

    if fake_records:
        perturbation_types.append("fake_files")
        distractor_files.extend(record.fake_file_path for record in fake_records)

    if hiding_record:
        perturbation_types.append("in_place_hiding")
        runtime_real_file = hiding_record.runtime_real_file
        semantic_anchor_files.append(hiding_record.hidden_real_file_path)
        distractor_files.extend([hiding_record.wrapper_package_path, hiding_record.wrapper_init_path])
        perturbations["in_place_hiding"] = {
            "whether_applied": True,
            **asdict(hiding_record),
        }
        perturbations["fake_files"]["real_runtime_file"] = hiding_record.runtime_real_file
    else:
        semantic_anchor_files.append(abs_path)

    return FilePerturbationRecord(
        original_file_path=abs_path,
        relative_file_path=normalize_relpath(abs_path, repo_root),
        file_language="python",
        extension=os.path.splitext(abs_path)[1],
        was_perturbed=bool(perturbation_types),
        perturbation_types=perturbation_types,
        source_reason="touched_by_gold_patch",
        runtime_real_file=runtime_real_file,
        semantic_anchor_files=sorted(set(semantic_anchor_files)),
        distractor_files=sorted(set(distractor_files)),
        perturbations=perturbations,
    )

def register_path_resolutions(record: FilePerturbationRecord, collector: RepoMirageMetadataCollector) -> None:
    proxy_meta = record.perturbations.get("proxy_import", {})
    for mapping in proxy_meta.get("proxy_mappings", []):
        collector.add_resolution(
            {
                "kind": "import_proxy",
                "visible_path": mapping["original_dependency"],
                "apparent_path": mapping["proxy_module"],
                "runtime_real_path": mapping["runtime_real_target"],
                "owner_file": record.original_file_path,
            }
        )

    dynamic_meta = record.perturbations.get("dynamic_dependency", {})
    for item in dynamic_meta.get("extracted_constants", []):
        location = item.get("source_code_location")
        visible_path = record.original_file_path
        if location:
            visible_path = f"{record.original_file_path}:{location['start_line']}"
        collector.add_resolution(
            {
                "kind": "dynamic_value",
                "visible_path": visible_path,
                "apparent_path": item["replacement_expression"],
                "runtime_real_path": f"{item['json_path']}#{item['json_key']}",
            }
        )

    hiding_meta = record.perturbations.get("in_place_hiding", {})
    if hiding_meta.get("whether_applied"):
        collector.add_resolution(
            {
                "kind": "wrapper_module",
                "visible_path": record.original_file_path,
                "apparent_path": hiding_meta["wrapper_init_path"],
                "runtime_real_path": hiding_meta["runtime_real_file"],
            }
        )

    fake_meta = record.perturbations.get("fake_files", {})
    for fake_path in fake_meta.get("fake_file_paths", []):
        collector.add_resolution(
            {
                "kind": "fake_file",
                "visible_path": fake_path,
                "apparent_path": fake_path,
                "runtime_real_path": record.runtime_real_file,
                "activation_status": "never_used_at_runtime",
            }
        )

def process_single_file(
    abs_path: str,
    repo_root: str,
    naming_plan: Optional[PerturbationNamingPlan] = None,
    enabled_perturbations: Optional[Set[str]] = None,
) -> Optional[Dict[str, Any]]:
    print(f"Processing: {os.path.basename(abs_path)}")
    try:
        code = read_text(abs_path)
        tree = cst.parse_module(code)
    except Exception as e:
        print(f"[ERR] Parse failed {abs_path}: {e}")
        return None

    dirname = os.path.dirname(abs_path)
    enabled_perturbations = enabled_perturbations or set(PERTURBATION_TYPES)

    const_tf = ConstantExtractorTransformer(dirname)
    if "dynamic_dependency" in enabled_perturbations:
        const_wrapper = cst.metadata.MetadataWrapper(tree)
        tree = const_wrapper.visit(const_tf)
        const_tf.finalize_json_layout()

    proxy_transformer = ImportProxyTransformer(dirname, repo_root)
    if "proxy_import" in enabled_perturbations:
        wrapper = cst.metadata.MetadataWrapper(tree)
        tree = wrapper.visit(proxy_transformer)
        if proxy_transformer.alias_map and len(proxy_transformer.alias_map):
            print(f"    -> Imports Renamed: {len(proxy_transformer.alias_map)}")

    if "proxy_import" in enabled_perturbations or (
        "dynamic_dependency" in enabled_perturbations and const_tf.changed
    ):
        tree = inject_header_code(tree)

    proxy_binding_collector = ProxyImportBindingCollector()
    tree.visit(proxy_binding_collector)
    fake_proxy_usage_scramble = build_fake_proxy_usage_scramble(proxy_binding_collector.bindings)
    decoy_info = {"whether_applied": False, "fake_file_records": []}
    if "fake_files" in enabled_perturbations and os.path.basename(abs_path) != "__init__.py":
        try:
            fake_tree = tree
            if fake_proxy_usage_scramble:
                fake_tree = cst.metadata.MetadataWrapper(fake_tree).visit(
                    FakeProxyUsageScrambleTransformer(fake_proxy_usage_scramble)
                )
            decoy_info = generate_decoy(abs_path, fake_tree, naming_plan=naming_plan)
            decoy_info["dependency_key_permutation"] = {}
            decoy_info["proxy_usage_scramble"] = dict(fake_proxy_usage_scramble)
            if decoy_info.get("whether_applied"):
                print("    -> Decoy file generated")
        except Exception:
            decoy_info = {
                "whether_applied": False,
                "fake_file_records": [],
                "dependency_key_permutation": {},
                "proxy_usage_scramble": dict(fake_proxy_usage_scramble),
            }

    if "dynamic_dependency" in enabled_perturbations and const_tf.extracted_constants:
        tree = tree.visit(
            DependencyKeySplitTransformer(
                [record.json_key for record in const_tf.extracted_constants]
            )
        )
        tree = tree.visit(
            DependencyStringSplitTransformer(
                [CONFIG_FILENAME, f"{CONFIG_FILENAME_PREFIX}_", ".json"]
            )
        )

    write_text(abs_path, tree.code)

    hiding_info = {"whether_applied": False}
    if "in_place_hiding" in enabled_perturbations and os.path.basename(abs_path) != "__init__.py":
        hiding_info = apply_sibling_shadow(abs_path, repo_root, naming_plan=naming_plan)

    record = build_file_record(abs_path, repo_root, const_tf, proxy_transformer, decoy_info, hiding_info)
    print(f"[DONE] {os.path.basename(abs_path)}\n")
    return {
        "record": record,
        "proxy_count": len(unique_paths([record.proxy_file_path for record in getattr(proxy_transformer, "proxy_records", [])])),
        "extracted_constant_count": len(const_tf.extracted_constants),
    }

def main():
    if len(sys.argv) < 2:
        print("Usage: python augment_ultra.py /path/to/files.txt [sample_context.json]")
        sys.exit(1)

    files_txt = sys.argv[1]
    sample_context_path = sys.argv[2] if len(sys.argv) > 2 else None
    if not os.path.exists(files_txt):
        return

    sample_context: Dict[str, Any] = {}
    if sample_context_path and os.path.exists(sample_context_path):
        sample_context = load_json_or_empty(sample_context_path)
    enabled_perturbations = normalize_enabled_perturbations(
        sample_context.get("enabled_perturbations")
    )

    with open(files_txt, 'r', encoding='utf-8') as f:
        files = [line.strip() for line in f if line.strip()]

    print(f"Targets: {len(files)}")

    target_files = sorted(list(set(files)))
    naming_plans = build_naming_plans(target_files)
    repo_root = sample_context.get("repo_path") or os.path.commonpath(target_files) if target_files else os.getcwd()
    sample_context.setdefault("repo_path", repo_root)
    sample_context.setdefault("mirage_repo_path", repo_root)
    sample_context.setdefault("patch_touched_files", [normalize_relpath(fp, repo_root) for fp in target_files])

    collector = RepoMirageMetadataCollector(sample_context)

    for fp in target_files:
        if fp.endswith('.py') and os.path.exists(fp):
            file_stats = process_single_file(
                fp,
                repo_root,
                naming_plan=naming_plans.get(fp),
                enabled_perturbations=enabled_perturbations,
            )
            if file_stats is None:
                continue
            collector.add_file_stats(
                proxy_count=file_stats.get("proxy_count", 0),
                extracted_constant_count=file_stats.get("extracted_constant_count", 0),
            )
            record = file_stats.get("record")
            if record is not None:
                collector.add_file_record(record)
                register_path_resolutions(record, collector)

    metadata = collector.build()
    metadata_output_path = sample_context.get("metadata_output_path")
    if metadata_output_path:
        os.makedirs(os.path.dirname(metadata_output_path), exist_ok=True)
        save_json(metadata_output_path, metadata)
        print(f"[METADATA] {metadata_output_path}")

    print("All tasks finished.")

if __name__ == '__main__':
    main()
"""
