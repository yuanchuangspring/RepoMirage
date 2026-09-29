# RepoMirage

Benchmark construction toolkit for repository-context reasoning in code agents. It takes SWE-bench instances, applies semantics-preserving repository perturbations, and turns the resulting structural bottlenecks into explicit, automatically checkable tasks.

🔥 Accepted by NeurIPS 2026 ED Track.

The whole pipeline is:

```
SWE-bench dataset → ① perturb (perturbed images) → ② extend (task images) → ③ export (datasets) → run agents → validate
```

All commands go through a single entry point, `cli.py`, run from the repository root. Intermediate files are written to `repomirage_output/` automatically — you never configure their paths.

## Requirements

* Docker, able to pull `swebench/sweb.eval.x86_64.*` base images
* Host Python packages: `pip install -r requirements.txt` (`docker`, `datasets`, `tqdm`)
* `RepoMirage_Perturb/wheels/` containing an offline `libcst` wheel (installed inside containers)
* A local SWE-bench dataset directory, default `./SWE-bench_Verified`

## Quick Start

```bash
# ① build perturbed images
python cli.py perturb --dataset-dir SWE-bench_Verified

# ② assign tasks and build task images
python cli.py extend

# ③ export task datasets for agent runners (optional)
python cli.py export
```

That's it. Every subcommand has `--help`.

First-run tips:

* **Smoke test**: `python cli.py perturb --limit 3` builds just three images.
* **No-Docker dry run**: `python cli.py extend summary` only writes task assignment lists.
* **Move all artifacts elsewhere**: set `REPOMIRAGE_OUT=/path/to/workspace`.

## What Gets Generated

```text
repomirage_output/
├── built_instances.json              # instances whose perturbed images were built
├── metadata/<instance_id>.json       # what was perturbed in each instance (bridge ① → ②)
├── tasks/
│   ├── proxy_top_144.json            # → Proxy Chain Completion
│   ├── constant_top_144.json         # → Missing Constant Recovery
│   ├── touched_files_gt1_<N>.json    # → Multi-File Issue Resolution
│   ├── remainder.json                # → Runtime Target Identification
│   └── *_generation_summary.json     # ground truth used for validation
├── datasets/                         # exported Hugging Face-style datasets (③)
└── reports/                          # validation reports
```

Docker images all live under `swebench/sweb.eval.x86_64.<instance_id>:<tag>`:

| Tag | Built by | Used for |
|---|---|---|
| `repomirage` | ① | Perturbed repositories; Multi-File Issue Resolution |
| `repomirage_proxy_chain` | ② | Proxy Chain Completion |
| `repomirage_runtime_target` | ② | Runtime Target Identification |
| `repomirage_missing_constant` | ② | Missing Constant Recovery |

## The Two Stages

### ① perturb

For each instance, starts the base image, applies four perturbation modules to the `.py` files touched by the gold patch, then exports metadata, removes it from the container, rebuilds the git history, and commits the new image tag.

| Module | Effect |
|---|---|
| `proxy_import` | rewrites direct imports through multi-hop proxy files |
| `in_place_hiding` | hides the real implementation behind a wrapper package |
| `fake_files` | adds decoy files that look like the real implementation |
| `dynamic_dependency` | moves constants out of code into JSON resources |

All four are enabled by default; pass `--only <module> ...` to enable a subset.

### ② extend

`summary` reads the metadata and assigns each instance to one of four task families:

* **Multi-File Issue Resolution** — gold patch touches more than one file; uses the ① image directly.
* **Proxy Chain Completion** — top-K instances by proxy count; the middle proxy files are erased and agents must rebuild the chain.
* **Missing Constant Recovery** — top-K instances by extracted constant count; JSON keys are removed and agents must recover them.
* **Runtime Target Identification** — remaining instances; the wrapper reference to the real implementation is removed and agents must pick it out from decoys.

The workflow then builds the task images for the last three families. Use `python cli.py extend summary` to skip image building, or pass steps explicitly, e.g. `python cli.py extend summary proxy`.

## Validating Agent Runs

After agents produce patch files, check them against the generation summaries:

```bash
python cli.py validate proxy    solutions.json repomirage_output/tasks/proxy_chain_generation_summary.json
python cli.py validate runtime  solutions.json repomirage_output/tasks/runtime_target_generation_summary.json
python cli.py validate constant solutions.json repomirage_output/tasks/missing_constant_generation_summary.json
```

`solutions.json` is a list of `{instance_id, patch}` objects or a dict keyed by `instance_id`; the patch field may be named `patch`, `agent_patch`, `completion_patch`, or `model_patch`. Reports are written to `repomirage_output/reports/`.

## Common Options

| Command | Option | Purpose |
|---|---|---|
| `perturb` | `--limit N` | process only N instances |
| `perturb` | `--instance-regex RE` | process only matching instance IDs |
| `perturb` | `--only NAME ...` | enable a subset of perturbation modules |
| `perturb` | `--force` | rebuild images even if the tag exists |
| `extend` | `--steps summary proxy runtime constant` | choose which steps to run |
| `extend` | `--proxy-top-k N`, `--constant-top-k N` | task family sizes (default 144) |
| `extend` | `--overwrite` | rebuild task images even if the tag exists |
| `export` | `--steps proxy_chain ...` | choose which datasets to export |
| all | `--seed N` | deterministic construction (default 42) |

## Repository Layout

```text
cli.py                     # single entry point
repomirage_common.py       # shared defaults: paths, tags, seeds
RepoMirage_Perturb/        # ① repomirage.py, augment_script.py, wheels/
RepoMirage_Extend/         # ② summary, generators, validators, extract_dataset/
```

The individual scripts still run standalone with the same defaults, and legacy option names (e.g. `--host-metadata-dir`, `--yes-con-output`) remain accepted as aliases.
