import argparse
import io
import os
import re
import sys
import tarfile
import tempfile
import threading
import shutil
import hashlib
try:
    import docker
except ModuleNotFoundError:
    docker = None

from augment_script import AUGMENT_SCRIPT
from pathlib import Path
try:
    from datasets import load_dataset
except ModuleNotFoundError:
    load_dataset = None
try:
    from tqdm import tqdm
except ModuleNotFoundError:
    tqdm = lambda iterable: iterable

import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from repomirage_common import (  # noqa: E402
    AUG_TAG,
    BUILT_INSTANCES_PATH,
    DEFAULT_DATASET_DIR,
    DEFAULT_SPLIT,
    GIT_USER_EMAIL,
    GIT_USER_NAME,
    METADATA_DIR,
    SEED,
)

PERTURB_DIR = Path(__file__).resolve().parent

DATASET_DIR = DEFAULT_DATASET_DIR
DATASET_SPLIT = DEFAULT_SPLIT
DEFAULT_METADATA_SUBDIR = ".repomirage/metadata"
DEFAULT_HOST_METADATA_DIR = str(METADATA_DIR)
DEFAULT_WHEELS_DIR = str(PERTURB_DIR / "wheels")
DEFAULT_YES_CON_OUTPUT = str(BUILT_INSTANCES_PATH)
DEFAULT_DOCKER_PULL_TIMEOUT = 120
DEFAULT_SEED = SEED
DEFAULT_GIT_USER_NAME = GIT_USER_NAME
DEFAULT_GIT_USER_EMAIL = GIT_USER_EMAIL
DEFAULT_COMMIT_MESSAGE = "Initialize RepoMirage-transformed repository"
PERTURBATION_TYPES = (
    "dynamic_dependency",
    "proxy_import",
    "fake_files",
    "in_place_hiding",
)

client = None


def get_docker_client():
    global client
    if docker is None:
        raise RuntimeError("Missing Python package 'docker'. Install it first, for example: pip install docker")
    if client is None:
        client = docker.from_env()
    return client

PATCH_FILE_RE = re.compile(r"^diff --git a/(.*?) b/(.*?)\s*$", re.MULTILINE)

def pull_with_timeout(image_tag: str, timeout_sec: int):
    result = {"ok": False, "error": None}

    def _pull():
        try:
            client.images.pull(image_tag)
            result["ok"] = True
        except Exception as e:
            result["error"] = e

    thread = threading.Thread(target=_pull)
    thread.start()
    thread.join(timeout=timeout_sec)

    if thread.is_alive():
        return False, f"Timeout after {timeout_sec}s"
    if result["ok"]:
        return True, None
    return False, result["error"]

def extract_modified_files(patch_text: str) -> list[str]:
    files = []
    for a_path, b_path in PATCH_FILE_RE.findall(patch_text):
        files.append(b_path)
    seen = set()
    out = []
    for f in files:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out

def instance_id_to_image(instance_id: str) -> str:
    docker_compatible = instance_id.replace("__", "_1776_")
    return f"swebench/sweb.eval.x86_64.{docker_compatible}:latest"

def ensure_image(image_tag: str, timeout_sec: int = DEFAULT_DOCKER_PULL_TIMEOUT):
    try:
        client.images.get(image_tag)
        return True
    except docker.errors.ImageNotFound:
        print(f"[pull] Pulling: {image_tag}")
        ok, err = pull_with_timeout(image_tag, timeout_sec)
        if ok:
            return True
        print(f"[error] Pull failed: {image_tag} - {err}")
        return False

def copy_dir_to_container(container, src_dir: Path, dest_dir: str):
    container.exec_run(f"mkdir -p {dest_dir}")
    tar_stream = io.BytesIO()
    with tarfile.open(fileobj=tar_stream, mode="w") as tar:
        for path in src_dir.rglob("*"):
            if path.is_file():
                arcname = str(path.relative_to(src_dir))
                tar.add(path, arcname=arcname)
    tar_stream.seek(0)
    container.put_archive(dest_dir, tar_stream.read())

def copy_file_from_container(container, container_file: str, host_file: Path) -> bool:
    host_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        stream, stat = container.get_archive(container_file)
    except Exception as e:
        print(f" [Metadata] Failed to fetch {container_file}: {e}")
        return False

    tar_bytes = io.BytesIO()
    for chunk in stream:
        tar_bytes.write(chunk)
    tar_bytes.seek(0)

    try:
        with tarfile.open(fileobj=tar_bytes) as tar:
            members = tar.getmembers()
            if not members:
                print(f" [Metadata] Empty archive for {container_file}")
                return False
            extracted = tar.extractfile(members[0])
            if extracted is None:
                print(f" [Metadata] Could not extract file for {container_file}")
                return False
            host_file.write_bytes(extracted.read())
            return True
    except Exception as e:
        print(f" [Metadata] Failed to unpack {container_file}: {e}")
        return False


def normalize_enabled_perturbations(selected: list[str] | None) -> list[str]:
    if not selected:
        return list(PERTURBATION_TYPES)

    normalized = []
    for item in selected:
        if item in PERTURBATION_TYPES and item not in normalized:
            normalized.append(item)
    return normalized or list(PERTURBATION_TYPES)

def build_sample_context(
    instance: dict,
    py_files: list[str],
    metadata_subdir: str = DEFAULT_METADATA_SUBDIR,
    enabled_perturbations: list[str] | None = None,
    seed: int = DEFAULT_SEED,
) -> dict:
    instance_id = instance["instance_id"]
    instance_seed = int(hashlib.sha1(f"{seed}:{instance_id}".encode("utf-8")).hexdigest()[:12], 16)
    repo_name = instance.get("repo") or instance.get("repo_name")
    metadata_output_path = f"/testbed/{metadata_subdir.strip('/')}/{instance_id}.json"
    patch_text = instance.get("patch", "")
    return {
        "instance_id": instance_id,
        "sample_id": instance_id,
        "repo_name": repo_name,
        "repo_path": "/testbed",
        "clean_repo_path": instance.get("clean_repo_path"),
        "mirage_repo_path": "/testbed",
        "gold_patch_path": instance.get("gold_patch_path"),
        "patch_source": "instance.patch",
        "patch_sha1": hashlib.sha1(patch_text.encode("utf-8")).hexdigest(),
        "patch_text": patch_text,
        "patch_touched_files": py_files,
        "metadata_output_path": metadata_output_path,
        "enabled_perturbations": normalize_enabled_perturbations(enabled_perturbations),
        "seed": instance_seed,
        "base_seed": seed,
    }

# Core image-building logic.

def augment_instance(
    instance: dict,
    metadata_subdir: str = DEFAULT_METADATA_SUBDIR,
    host_metadata_dir: str | Path = DEFAULT_HOST_METADATA_DIR,
    enabled_perturbations: list[str] | None = None,
    aug_tag: str = AUG_TAG,
    wheels_dir: str | Path = DEFAULT_WHEELS_DIR,
    docker_pull_timeout: int = DEFAULT_DOCKER_PULL_TIMEOUT,
    git_user_name: str = DEFAULT_GIT_USER_NAME,
    git_user_email: str = DEFAULT_GIT_USER_EMAIL,
    commit_message: str = DEFAULT_COMMIT_MESSAGE,
    seed: int = DEFAULT_SEED,
    force: bool = False,
) -> str | None:
    instance_id = instance["instance_id"]
    patch = instance.get("patch", "")

    # 1) Analyze Python files touched by the patch.
    modified_files = extract_modified_files(patch)
    py_files = [f for f in modified_files if f.endswith(".py")]

    if not py_files:
        return None

    # 2) Prepare Docker image tags.
    base_image = instance_id_to_image(instance_id)
    base_repo, _ = base_image.split(":")
    augmented_tag = f"{base_repo}:{aug_tag}"

    if not force:
        try:
            client.images.get(augmented_tag)
            print(f" [Skip] Already exists: {augmented_tag}")
            return augmented_tag
        except docker.errors.ImageNotFound:
            pass

    print(f"\n=== Processing {instance_id} ===")
    print(f" Targets: {py_files}")

    if not ensure_image(base_image, timeout_sec=docker_pull_timeout):
        return None

    container = None
    try:
        container = client.containers.run(
            base_image,
            command="sleep infinity",
            user="root", 
            detach=True,
            init=True,
        )

        # 4) Prepare the in-container augmentation script.
        tmp_dir = Path(tempfile.mkdtemp(prefix="sb_aug_"))
        augment_dir = tmp_dir
        
        files_txt = augment_dir / "files.txt"
        with files_txt.open("w", encoding="utf-8") as f:
            for rel_path in py_files:
                # SWE-bench images place the repository at /testbed.
                container_path = f"/testbed/{rel_path}"
                f.write(container_path + "\n")

        sample_context = build_sample_context(
            instance,
            py_files,
            metadata_subdir=metadata_subdir,
            enabled_perturbations=enabled_perturbations,
            seed=seed,
        )
        sample_context_path = augment_dir / "sample_context.json"
        sample_context_path.write_text(json.dumps(sample_context, indent=2), encoding="utf-8")
        host_metadata_path = Path(host_metadata_dir) / f"{instance_id}.json"

        aug_py = augment_dir / "augment_in_container.py"
        aug_py.write_text(AUGMENT_SCRIPT, encoding="utf-8")

        local_wheels_dir = Path(wheels_dir)
        bundled_wheels_dir = augment_dir / "wheels"

        if not local_wheels_dir.is_dir():
            print(f" [Fatal] Wheels dir not found: {local_wheels_dir}")
            print("         Put an installable libcst wheel in RepoMirage_Perturb/wheels/ or pass --wheels-dir.")
            return None

        shutil.copytree(local_wheels_dir, bundled_wheels_dir)

        # 5) Copy the script and wheel directory into the container.
        copy_dir_to_container(container, augment_dir, "/tmp/augment")

        print(" [+] Installing libcst from bundled wheels...")
        res = container.exec_run(
            "python -m pip install --no-index --find-links=/tmp/augment/wheels libcst"
        )
        if res.exit_code != 0:
            print(f" [!] Failed to install libcst from local wheels:\n{res.output.decode(errors='ignore')}")
            print(" [Fatal] Could not install libcst inside container. Aborting.")
            return None

        cmd = "python /tmp/augment/augment_in_container.py /tmp/augment/files.txt /tmp/augment/sample_context.json"
        print(" [*] Running augmentation logic...")
        exit_code, output = container.exec_run(cmd)
        
        logs = output.decode("utf-8", errors="ignore")

        has_import_mod = "Imports Renamed" in logs
        has_const_mod = "Mod Constant" in logs

        # Print only key logs to keep host output readable.
        if exit_code != 0:
            print(f" [Error Log]\n{logs}")
            print(" [!] Script failed. Skipping commit.")
            return None

        if copy_file_from_container(container, sample_context["metadata_output_path"], host_metadata_path):
            print(f" [Metadata] Exported to {host_metadata_path}")
        else:
            print(f" [Metadata] Export failed for {instance_id}")

        metadata_root = str(Path(sample_context["metadata_output_path"]).parent.parent)
        cleanup_res = container.exec_run(f"rm -rf {metadata_root}", user="root")
        if cleanup_res.exit_code == 0:
            print(f" [Metadata] Removed in-container metadata dir: {metadata_root}")
        else:
            print(
                f" [Metadata] Failed to remove in-container metadata dir {metadata_root}: "
                f"{cleanup_res.output.decode(errors='ignore')}"
            )

        print(" [Git] Rebuilding repository history from scratch...")

        res_rm_git = container.exec_run("rm -rf /testbed/.git", user="root")
        if res_rm_git.exit_code != 0:
            print(f" [Git Error] Failed to remove original .git: {res_rm_git.output.decode(errors='ignore')}")
            return None

        res_init = container.exec_run("git init", workdir="/testbed")
        if res_init.exit_code != 0:
            print(f" [Git Error] Init failed: {res_init.output.decode(errors='ignore')}")
            return None

        container.exec_run("git branch -M main", workdir="/testbed")
        container.exec_run(f"git config user.email {json.dumps(git_user_email)}", workdir="/testbed")
        container.exec_run(f"git config user.name {json.dumps(git_user_name)}", workdir="/testbed")

        git_add_cmd = "git add -A"
        res_add = container.exec_run(git_add_cmd, workdir="/testbed")

        if res_add.exit_code != 0:
            print(f" [Git Error] Add failed: {res_add.output.decode()}")
            return None

        git_commit_cmd = f"git commit -m {json.dumps(commit_message)}"
        res_commit = container.exec_run(git_commit_cmd, workdir="/testbed")
        
        if res_commit.exit_code != 0:
            if "nothing to commit" not in res_commit.output.decode():
                print(f" [Git Error] Commit failed: {res_commit.output.decode()}")
                return None
            else:
                print(" [Git] Nothing to commit (weird but okay).")
        else:
            print(" [Git] Obfuscation committed successfully.")

        # if has_import_mod or has_const_mod:
        if True:
            container.commit(repository=base_repo, tag=aug_tag)
            print(f" [ok] Committed: {augmented_tag}")
            return "YES_CON"
        else:
            print(f" [skip] Skip: {augmented_tag}")
            return augmented_tag

    except Exception as e:
        print(f" [Exception] {e}")
        return None

    finally:
        if container:
            try:
                container.kill()
                container.remove()
            except:
                pass
            # print(" [x] Container cleaned")

def main():
    parser = argparse.ArgumentParser(description="Build RepoMirage-transformed SWE-bench Docker images.")
    parser.add_argument("--dataset-dir", default=DATASET_DIR)
    parser.add_argument("--split", default=DATASET_SPLIT)
    parser.add_argument("--aug-tag", default=AUG_TAG)
    parser.add_argument("--metadata-subdir", default=DEFAULT_METADATA_SUBDIR)
    parser.add_argument(
        "--metadata-dir",
        dest="host_metadata_dir",
        default=DEFAULT_HOST_METADATA_DIR,
        help="Host directory for exported metadata JSON files. Default: repomirage_output/metadata.",
    )
    parser.add_argument("--host-metadata-dir", dest="host_metadata_dir", help=argparse.SUPPRESS)
    parser.add_argument(
        "--wheels-dir",
        default=DEFAULT_WHEELS_DIR,
        help="Local offline wheel directory. Default: RepoMirage_Perturb/wheels.",
    )
    parser.add_argument(
        "--built-instances-output",
        dest="yes_con_output",
        default=DEFAULT_YES_CON_OUTPUT,
        help="JSON file listing instances whose images were built. Default: repomirage_output/built_instances.json.",
    )
    parser.add_argument("--yes-con-output", dest="yes_con_output", help=argparse.SUPPRESS)
    parser.add_argument("--docker-pull-timeout", type=int, default=DEFAULT_DOCKER_PULL_TIMEOUT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--git-user-name", default=DEFAULT_GIT_USER_NAME)
    parser.add_argument("--git-user-email", default=DEFAULT_GIT_USER_EMAIL)
    parser.add_argument("--commit-message", default=DEFAULT_COMMIT_MESSAGE)
    parser.add_argument("--instance-regex", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force", action="store_true", help="Rebuild images even if the target tag already exists.")
    parser.add_argument(
        "--only",
        nargs="+",
        choices=PERTURBATION_TYPES,
        help="Only apply the listed perturbation types for ablation.",
    )
    args = parser.parse_args()

    wheels_dir = Path(args.wheels_dir)
    if not wheels_dir.is_dir():
        cwd_wheels = Path.cwd() / "wheels"
        if cwd_wheels.is_dir():
            wheels_dir = cwd_wheels
            args.wheels_dir = str(wheels_dir)
            print(f"[wheels] Using fallback wheels dir: {wheels_dir}")

    get_docker_client()
    if load_dataset is None:
        raise RuntimeError("Missing Python package 'datasets'. Install it first, for example: pip install datasets")

    if not os.path.exists(args.dataset_dir):
        print(f"Dataset dir {args.dataset_dir} not found.")
        return

    ds = load_dataset(str(args.dataset_dir), split=args.split)
    print(f"Loaded {len(ds)} instances.")

    enabled_perturbations = normalize_enabled_perturbations(args.only)
    print(f"Enabled perturbations: {enabled_perturbations}")

    success_count = 0
    yes_con = []
    compiled_regex = re.compile(args.instance_regex) if args.instance_regex else None
    processed = 0
    # Show progress with tqdm when available.
    for instance in tqdm(ds):
        instance_id = instance["instance_id"]
        if compiled_regex and not compiled_regex.search(instance_id):
            continue
        tag = augment_instance(
            instance,
            metadata_subdir=args.metadata_subdir,
            host_metadata_dir=args.host_metadata_dir,
            enabled_perturbations=enabled_perturbations,
            aug_tag=args.aug_tag,
            wheels_dir=args.wheels_dir,
            docker_pull_timeout=args.docker_pull_timeout,
            git_user_name=args.git_user_name,
            git_user_email=args.git_user_email,
            commit_message=args.commit_message,
            seed=args.seed,
            force=args.force,
        )
        if tag:
            success_count += 1
        if tag == "YES_CON":
            yes_con.append(instance["instance_id"])
        processed += 1
        if args.limit is not None and processed >= args.limit:
            break

    yes_con_path = Path(args.yes_con_output)
    yes_con_path.parent.mkdir(parents=True, exist_ok=True)
    with open(yes_con_path, "w", encoding="utf-8") as f:
        json.dump(yes_con, f)

    print(f"\n=== Done. Total augmented: {len(yes_con)} ===")
    print(f"Built instance list: {yes_con_path}")
    print(f"Metadata exported to: {Path(args.host_metadata_dir)}")

if __name__ == "__main__":
    main()
