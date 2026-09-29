"""Shared defaults and path conventions for the RepoMirage toolkit.

Every intermediate artifact produced by the pipeline defaults into one
workspace directory so that users never have to configure where files go:

    <repository>/repomirage_output/
        metadata/                      per-instance perturbation metadata
        tasks/                         task assignment lists and generation summaries
        datasets/                      optional Hugging Face-style datasets
        reports/                       validation reports
        built_instances.json           instances whose perturbed images were built

Override the workspace location with the REPOMIRAGE_OUT environment variable,
for example:

    REPOMIRAGE_OUT=/mnt/data/repomirage python cli.py perturb ...

Individual scripts still accept explicit paths through their command-line
options; those take precedence over the defaults defined here.
"""

from __future__ import annotations

import os
from pathlib import Path

# Repository root: the directory that contains this file.
REPO_ROOT = Path(__file__).resolve().parent


def _resolve_workspace() -> Path:
    override = os.environ.get("REPOMIRAGE_OUT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return REPO_ROOT / "repomirage_output"


WORKSPACE_DIR = _resolve_workspace()

# Output directories inside the workspace.
METADATA_DIR = WORKSPACE_DIR / "metadata"      # RepoMirage-Perturb exports -> RepoMirage-Extend consumes
TASKS_DIR = WORKSPACE_DIR / "tasks"            # task assignment lists + image generation summaries
DATASETS_DIR = WORKSPACE_DIR / "datasets"      # exported Hugging Face-style datasets
REPORTS_DIR = WORKSPACE_DIR / "reports"        # validation reports

# List of instance_ids whose perturbed images were successfully built
# (kept outside metadata/ because every *.json there is read as instance metadata).
BUILT_INSTANCES_PATH = WORKSPACE_DIR / "built_instances.json"

# Docker image tags used across the pipeline.
AUG_TAG = "repomirage"                                  # perturbed base images (Part 1)
PROXY_TARGET_TAG = "repomirage_proxy_chain"             # Proxy Chain Completion images
RUNTIME_TARGET_TAG = "repomirage_runtime_target"        # Runtime Target Identification images
CONSTANT_TARGET_TAG = "repomirage_missing_constant"     # Missing Constant Recovery images
IMAGE_PREFIX = "swebench/sweb.eval.x86_64."

# Task family sizes and shared knobs.
PROXY_TOP_K = 144
CONSTANT_TOP_K = 144
SEED = 42
PLACEHOLDER = "YOUR CODE HERE"
CONSTANT_SAMPLE_SIZE = 5

# Git identity used for commits made inside generated Docker images.
GIT_USER_NAME = "RepoMirage"
GIT_USER_EMAIL = "repomirage@example.invalid"

# Default local SWE-bench dataset directory / HF dataset name.
DEFAULT_DATASET_DIR = "SWE-bench_Verified"
DEFAULT_SPLIT = "test"
