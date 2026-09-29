# RepoMirage: Measuring Repository Context Reasoning Beyond Issue Resolution in Code Agents

## 📰 News

🔥 RepoMirage has been accepted by NeurIPS 2026 ED Track!

---

RepoMirage is a benchmark-generation and evaluation toolkit for probing repository-context reasoning in code agents. It builds on SWE-bench-style repository environments and introduces controlled repository-level perturbations that preserve task semantics while increasing the need to trace cross-file structure, runtime targets, proxy imports, and externalized constants.

The toolkit supports two complementary stages:

1. **RepoMirage-Perturb** applies semantics-preserving repository transformations to existing benchmark instances while keeping the original issue-resolution objective and evaluation protocol.
2. **RepoMirage-Extend** turns the structural bottlenecks introduced by perturbation into explicit benchmark tasks, making repository-context reasoning easier to measure directly.

This repository is released as an executable benchmark-construction toolkit rather than a static dataset. It does not redistribute modified benchmark repositories or Docker images. Instead, it reconstructs perturbed repositories and derived task environments from existing SWE-bench-compatible Docker images.

All commands in this README go through a single entry point, `cli.py`, run from the repository root. Intermediate artifacts are written to a `repomirage_output/` workspace automatically — you never need to configure their paths.

## 📦 Requirements

* Docker is running and accessible from the current user.
* SWE-bench-compatible base Docker images are prepared (they are pulled automatically when missing).
* Host Python packages (install with `pip install -r requirements.txt`):

  * `docker`
  * `datasets`
  * `tqdm`

* `RepoMirage_Perturb/` expects a local `wheels/` directory (inside `RepoMirage_Perturb/`) containing an installable `libcst` wheel and any required offline dependencies.
* A local SWE-bench dataset directory (e.g. `SWE-bench_Verified/` at the repository root) or a Hugging Face dataset name.

## 🚀 Quick Start

From the repository root, the full workflow is three commands:

```bash
# Step 1: build perturbed repository images (metadata is exported automatically)
python cli.py perturb --dataset-dir SWE-bench_Verified

# Step 2: assign tasks and build task-specific images
python cli.py extend

# Step 3 (optional): export task lists as local Hugging Face-style datasets
python cli.py export
```

That is all. Every intermediate file lands in `repomirage_output/` (see [Output Workspace](#-output-workspace) below) and the generated Docker images are tagged per task family (see [Docker Image Tags](#docker-image-tags)).

### First-run tips

* **Dry run without Docker** — step 2 has a `summary`-only mode that writes task assignment lists without building any image:

  ```bash
  python cli.py extend summary
  ```

* **Smoke test on a few instances** — add `--limit 3` to step 1 to build only three perturbed images before running the full benchmark.
* **Work on a subset** — `python cli.py perturb --instance-regex 'django__'` processes only matching instance IDs.
* **Relocate all artifacts** — set the `REPOMIRAGE_OUT` environment variable (e.g. `REPOMIRAGE_OUT=/mnt/data/repomirage python cli.py perturb ...`).

## 📂 Output Workspace

The toolkit never asks you where to put intermediate files. Everything is written under `repomirage_output/` at the repository root (or under `REPOMIRAGE_OUT` if set):

```text
repomirage_output/
├── built_instances.json            # instance IDs whose perturbed images were built
├── metadata/                       # per-instance perturbation metadata
│   └── <instance_id>.json
├── tasks/                          # task assignment lists + image generation summaries
│   ├── proxy_top_144.json          # Proxy Chain Completion instances
│   ├── constant_top_144.json       # Missing Constant Recovery instances
│   ├── touched_files_gt1_<N>.json  # Multi-File Issue Resolution instances
│   ├── remainder.json              # Runtime Target Identification instances
│   ├── summary_index.json          # all per-instance summaries
│   ├── group_summary.json          # group sizes / assignment statistics
│   └── *_generation_summary.json   # per-step summaries used later for validation
├── datasets/                       # (optional) exported Hugging Face-style datasets
│   ├── repomirage_multifile/
│   ├── repomirage_proxy_chain/
│   ├── repomirage_runtime_target/
│   └── repomirage_missing_constant/
└── reports/                        # validation reports for agent repair patches
```

| Artifact | Produced by | Purpose |
|---|---|---|
| `metadata/*.json` | Step 1 | Describes exactly which perturbations were applied to each instance. It is the bridge between Perturb and Extend. |
| `built_instances.json` | Step 1 | Lists instances whose images were successfully built; handy for resuming or filtering later steps. |
| `tasks/*.json` | Step 2 (`summary`) | Assigns each instance to a task family and records how its task image was generated. |
| `datasets/*/` | Step 3 | Ready-to-load datasets for agent runners, with `docker_image` columns pointing at the generated images. |
| `reports/*.json` | Validation | Per-solution validation results after an agent run. |

### Docker Image Tags

Images built by the toolkit share the SWE-bench prefix `swebench/sweb.eval.x86_64.<instance_id>` and differ only in their tag:

| Tag | Built by | Used for |
|---|---|---|
| `repomirage` | Step 1 | Perturbed repository images; Multi-File Issue Resolution |
| `repomirage_proxy_chain` | Step 2 | Proxy Chain Completion |
| `repomirage_runtime_target` | Step 2 | Runtime Target Identification |
| `repomirage_missing_constant` | Step 2 | Missing Constant Recovery |

## 🧩 What Each Stage Does

### RepoMirage-Perturb (Step 1)

Loads SWE-bench instances, starts the corresponding base Docker images, applies repository-level perturbations inside each container, exports per-instance metadata, removes the metadata from the committed image, and records which images were built successfully.

Four construction modules are supported (all enabled by default):

* `proxy_import`: rewrites direct imports through multi-hop proxy files, making dependency paths less locally visible.
* `in_place_hiding`: masks the original runtime target behind a wrapper package and renamed implementation file.
* `fake_files`: adds nearby decoy files that are superficially similar to the real runtime file but differ in behaviorally meaningful details.
* `dynamic_dependency`: externalizes local constant values into JSON resources loaded at runtime.

Use `--only <module> [<module> ...]` to enable only a subset (useful for ablations).

### RepoMirage-Extend (Step 2)

Reads the metadata exported by Step 1 and assigns instances to four benchmark task families:

* **Multi-File Issue Resolution** — retains issue-resolution instances whose gold patches modify more than one file.
* **Proxy Chain Completion** — erases intermediate proxy files and requires agents to reconstruct the missing dependency-routing logic.
* **Runtime Target Identification** — removes the wrapper reference to the real runtime file and requires agents to distinguish the true implementation from decoys.
* **Missing Constant Recovery** — removes selected JSON keys while preserving values, requiring agents to recover cross-file key-value associations.

`python cli.py extend` runs task assignment and then builds the task images for Proxy Chain Completion, Runtime Target Identification, and Missing Constant Recovery. Use `python cli.py extend summary` to only produce task assignment lists.

### Dataset Export (Step 3, optional)

Converts the task lists into local Hugging Face-style dataset folders for mini-swe-agent-style runners. Each exported row is copied from the source SWE-bench dataset and gains three columns:

* `repomirage_task_type`
* `image_name`
* `docker_image`

Downstream runners select the generated task image through these fields. Export all families with `python cli.py export`, or a single one with e.g. `python cli.py export proxy_chain`.

## 📖 Command Reference

Every subcommand accepts `--help` (e.g. `python cli.py perturb --help`) and lists all of its options. The tables below cover the ones you are most likely to need.

### `python cli.py perturb`

| Option | Default | Description |
|---|---|---|
| `--dataset-dir` | `SWE-bench_Verified` | Dataset path or Hugging Face dataset name. |
| `--split` | `test` | Dataset split. |
| `--limit N` | all | Stop after N matching instances (useful for smoke tests). |
| `--instance-regex RE` | — | Only process matching instance IDs. |
| `--only NAME [NAME ...]` | all four | Only apply the listed perturbation modules. |
| `--aug-tag TAG` | `repomirage` | Docker tag for transformed images. |
| `--force` | off | Rebuild even if the target tag already exists. |
| `--seed N` | `42` | Base seed; per-instance seeds are derived deterministically. |

### `python cli.py extend [STEPS...]`

`STEPS` may be any of `summary`, `proxy`, `runtime`, `constant` (default: all four). For example, `python cli.py extend summary` produces task lists without touching Docker.

| Option | Default | Description |
|---|---|---|
| `--proxy-top-k N` | `144` | Number of Proxy Chain Completion instances. |
| `--constant-top-k N` | `144` | Number of Missing Constant Recovery instances. |
| `--source-tag TAG` | `repomirage` | Docker source tag from Step 1. |
| `--proxy-target-tag` / `--runtime-target-tag` / `--constant-target-tag` | see tags table | Target tags for task images. |
| `--instance-ids-file FILE` | — | Restrict to instance IDs listed in a text file. |
| `--overwrite` | off | Rebuild task images even if the tag already exists. |
| `--seed N` | `42` | Random seed for deterministic instance edits. |

### `python cli.py export [TASKS...]`

`TASKS` may be any of `multi_file`, `proxy_chain`, `runtime_target`, `missing_constant` (default: all four).

| Option | Default | Description |
|---|---|---|
| `--input-dataset` | `SWE-bench_Verified` | Source SWE-bench dataset path or HF dataset name. |
| `--overwrite` | off | Overwrite existing dataset folders. |

### `python cli.py validate TASK SOLUTIONS.json FEEDBACK.json`

Validates agent-submitted repair patches. `TASK` is one of `proxy`, `runtime`, `constant`; `FEEDBACK.json` is the matching generation summary from `repomirage_output/tasks/`:

```bash
python cli.py validate proxy    solutions.json repomirage_output/tasks/proxy_chain_generation_summary.json
python cli.py validate runtime  solutions.json repomirage_output/tasks/runtime_target_generation_summary.json
python cli.py validate constant solutions.json repomirage_output/tasks/missing_constant_generation_summary.json
```

`solutions.json` can be either a list of solution objects or an object keyed by `instance_id`. Each solution entry should include a patch field such as `patch`, `agent_patch`, `completion_patch`, or `model_patch`. Reports are written to `repomirage_output/reports/`.

## 🧰 Repository Structure

```text
.
|-- cli.py                       # unified entry point (perturb / extend / export / validate)
|-- repomirage_common.py         # shared defaults (paths, tags, seeds)
|-- requirements.txt
|-- RepoMirage_Perturb/          # Step 1: build perturbed repository images and export metadata
|   |-- repomirage.py
|   |-- augment_script.py        # in-container perturbation logic
|   `-- wheels/                  # (user-provided) offline libcst wheel
`-- RepoMirage_Extend/           # Step 2: task assignment, task images, validation
    |-- summary.py
    |-- run_extend_workflow.py
    |-- ProxyChain.py
    |-- RuntimeTarget.py
    |-- MissingConstant.py
    |-- validate_*.py
    `-- extract_dataset/         # Step 3: export Hugging Face-style datasets
```

## ⚙️ Advanced: Running Individual Scripts Directly

The top-level `cli.py` simply forwards to the scripts above, so every script can still be run on its own with the same defaults (for example from `RepoMirage_Extend/`):

```bash
python summary.py                                  # same defaults as `cli.py extend summary`
python ProxyChain.py                               # defaults read repomirage_output/ directly
python run_extend_workflow.py --steps summary proxy
python validate_ProxyChain.py solutions.json ../repomirage_output/tasks/proxy_chain_generation_summary.json
```

Artifact paths default into `repomirage_output/` regardless of the directory you run from; every script accepts explicit overrides and `--help`. Legacy option names (e.g. `--host-metadata-dir`, `--yes-con-output`, `--output-dir`) are still accepted as aliases.

## 🔬 Reproducibility Notes

* RepoMirage operates on existing SWE-bench-compatible Docker environments.
* The toolkit reconstructs perturbed repositories and derived tasks through deterministic scripts.
* Metadata exported during perturbation is the bridge between RepoMirage-Perturb and RepoMirage-Extend.
* Derived tasks are designed to be automatically checkable by deterministic validation scripts.
* For repeatable construction, use a fixed `--seed`. The default seed is `42` for both stages. Perturbation seeds are derived from the base seed and `instance_id`, so each instance is deterministic independent of dataset iteration order.
