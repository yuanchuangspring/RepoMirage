<p align="center">
  <img src="assets/repomirage-band.png" alt="RepoMirage" width="80%">
</p>

<div align="center">
  <h1>🔮 RepoMirage</h1>
</div>

<p align="center">
  <a href="https://arxiv.org/abs/2605.26177">
    <img alt="arXiv" src="https://img.shields.io/badge/arXiv-2605.26177-B31B1B.svg">
  </a>
  <a href="https://neurips.cc/">
    <img alt="NeurIPS 2026 ED Track" src="https://img.shields.io/badge/NeurIPS%202026-ED%20Track-8A2BE2">
  </a>
  <a href="https://www.python.org/">
    <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-1f425f.svg?color=purple">
  </a>
  <a href="https://github.com/yuanchuangspring/RepoMirage/blob/main/LICENSE">
    <img alt="License" src="https://img.shields.io/badge/License-MIT-blue">
  </a>
</p>

## 📰 News

* **[Accepted]** RepoMirage has been accepted by **NeurIPS 2026 E&D Track**! 🔥

## 👋 Overview

RepoMirage is a benchmark-construction toolkit for measuring **repository-context reasoning** in code agents: the ability to trace cross-file structure, hidden runtime targets, proxy imports, and externalized constants. It has two complementary stages:

1. **RepoMirage-Perturb** — applies *semantics-preserving repository perturbations* to issue-resolution instances. The issue, the gold patch, and the tests stay untouched; the repository structure becomes harder to reason about.
2. **RepoMirage-Extend** — turns the structural bottlenecks introduced by perturbation into four explicit, automatically checkable task families.

## 🚀 Quick Start

The commands below use the official SWE-bench (Verified); any SWE-bench-format dataset works the same way (Verified, Lite, the full set, or one built with [SWE-smith](https://github.com/SWE-bench/SWE-smith)).

### 0. Prerequisites

* An `x86_64` machine with at least ~120 GB of free disk — SWE-bench-format images are large.
* Docker, with your user allowed to run it ([Linux post-install steps](https://docs.docker.com/engine/install/linux-postinstall/)).
* Python 3.10+.

### 1. Install

```bash
git clone https://github.com/yuanchuangspring/RepoMirage.git
cd RepoMirage
pip install -r requirements.txt
```

### 2. Get a dataset

Download SWE-bench (Verified) into the default location, `./SWE-bench_Verified`:

```python
from datasets import load_dataset
load_dataset("SWE-bench/SWE-bench_Verified", split="test").save_to_disk("SWE-bench_Verified")
```

> [!NOTE]
> For any other dataset, point `--dataset-dir` at it (a local directory or a Hugging Face dataset id).

### 3. Bundle the offline `libcst` wheels

The perturbation runs inside containers with no network access, so `libcst` — **together with its dependencies** — must be bundled locally. The containers often run a different Python version than your host, so download wheels for every version the images may use (3.8–3.12 here):

```bash
mkdir -p RepoMirage_Perturb/wheels
for v in 38 39 310 311 312; do
  pip download libcst --only-binary=:all: \
    --platform manylinux2014_x86_64 --python-version $v \
    -d RepoMirage_Perturb/wheels
done
```

`manylinux2014` wheels run on glibc ≥ 2.17, which covers all SWE-bench images. (A plain `pip download libcst -d RepoMirage_Perturb/wheels` also works, but only for your host's Python version.)

### 4. Run the pipeline

From the repository root:

```bash
# ① Build perturbed repositories (metadata is exported automatically)
python cli.py perturb

# ② Assign tasks and build task images
python cli.py extend

# ③ Export task datasets for agent runners
python cli.py export
```

* Pre-warm base images to avoid waiting during the run (optional):

  ```bash
  docker pull swebench/sweb.eval.x86_64.django_1776_django-10914:latest   # example instance
  ```
* `② extend` first groups instances into task families, then builds the task-specific images. `python cli.py extend summary` writes the task lists only (no Docker).
* On tiny subsets some task families may end up empty — `②` and `③` simply skip them.
* Every subcommand has `--help`; see [Common Options](#-common-options).

## ✅ Validating Agent Runs

`solutions.json` is the output of your agent runner and follows **mini-swe-agent's `preds.json` format**: a JSON object keyed by `instance_id`, where each entry carries the generated patch in `model_patch` (see the [mini-swe-agent output docs](https://mini-swe-agent.com/v2/usage/output_files/)). A list of `{instance_id, ...}` entries is also accepted, and the patch field may be named `patch`, `agent_patch`, `completion_patch`, or `model_patch`.

```bash
python cli.py validate proxy    solutions.json repomirage_output/tasks/proxy_chain_generation_summary.json
python cli.py validate runtime  solutions.json repomirage_output/tasks/runtime_target_generation_summary.json
python cli.py validate constant solutions.json repomirage_output/tasks/missing_constant_generation_summary.json
```

Each validator applies the agent's patch to the task image, checks that only the intended files were touched, and runs targeted runtime checks. Reports go to `repomirage_output/reports/`.

## 🧩 Task Families

During `extend summary`, every perturbed instance is assigned to exactly one of four families, by priority:

| Family | Selection | Agent task |
|---|---|---|
| **Multi-File Issue Resolution** | gold patch touches > 1 file | solve the original issue on the perturbed repo |
| **Proxy Chain Completion** | top-K by proxy count | reconstruct erased middle-layer proxy files |
| **Runtime Target Identification** | the remaining instances | find the real implementation among decoys |
| **Missing Constant Recovery** | top-K by extracted constants | recover removed JSON keys while preserving values |

The two top-K families each take **K instances**, ranked by how heavily the corresponding perturbation hit them. Set K with `--proxy-top-k` / `--constant-top-k` (or pick instances by hand with `--instance-ids-file`); the task lists are named after the K you chose.

Perturbation modules behind all of this (all enabled by default, `--only` to select):

* `proxy_import` — rewrites direct imports through multi-hop proxy files
* `in_place_hiding` — hides the real implementation behind a wrapper package
* `fake_files` — adds decoy files that look like the real implementation
* `dynamic_dependency` — moves constants out of code into JSON resources

## 📂 What Gets Generated

```text
repomirage_output/
├── built_instances.json              # instances whose perturbed images were built
├── metadata/<instance_id>.json       # what was perturbed per instance (bridge ① → ②)
├── tasks/
│   ├── proxy_top_<K>.json            # → Proxy Chain Completion
│   ├── constant_top_<K>.json         # → Missing Constant Recovery
│   ├── touched_files_gt1_<N>.json    # → Multi-File Issue Resolution
│   ├── remainder.json                # → Runtime Target Identification
│   └── *_generation_summary.json     # ground truth used for validation
├── datasets/                         # exported Hugging Face-style datasets (③)
└── reports/                          # validation reports
```

All generated images keep the instance's image prefix and differ only by tag:

| Tag | Built by | Used for |
|---|---|---|
| `repomirage` | ① | Perturbed repositories; Multi-File Issue Resolution |
| `repomirage_proxy_chain` | ② | Proxy Chain Completion |
| `repomirage_runtime_target` | ② | Runtime Target Identification |
| `repomirage_missing_constant` | ② | Missing Constant Recovery |

## 🔧 Common Options

| Command | Option | Purpose |
|---|---|---|
| `perturb` | `--dataset-dir PATH` | dataset path or HF id (default `./SWE-bench_Verified`) |
| `perturb` | `--limit N` | process only N instances |
| `perturb` | `--instance-regex RE` | process only matching instance IDs |
| `perturb` | `--only NAME ...` | enable a subset of perturbation modules |
| `perturb` | `--force` | rebuild images even if the tag exists |
| `extend` | `--steps summary proxy runtime constant` | choose which steps to run |
| `extend` | `--proxy-top-k N` / `--constant-top-k N` | task family sizes (default 144) |
| `extend` | `--instance-ids-file FILE` | assign tasks only for the listed instance IDs |
| `extend` | `--overwrite` | rebuild task images even if the tag exists |
| `export` | `--steps proxy_chain ...` | choose which datasets to export |
| all | `--seed N` | deterministic construction (default 42) |

## 🧰 Repository Layout

```text
cli.py                     # single entry point (perturb / extend / export / validate)
repomirage_common.py       # shared defaults: paths, tags, seeds
RepoMirage_Perturb/        # ① repomirage.py, augment_script.py, wheels/
RepoMirage_Extend/         # ② summary, generators, validators, extract_dataset/
```

## ✍️ License & Acknowledgments

MIT License — see [`LICENSE`](LICENSE). RepoMirage builds on SWE-bench (MIT) and mini-swe-agent (MIT); it does not redistribute modified repositories or Docker images. See [`ASSETS.md`](ASSETS.md) for the full license notes.

## 📄 Citation

```bibtex
@misc{li2026repomirage,
      title={RepoMirage: Probing Repository Context Reasoning in Code Agents with Perturbations},
      author={Hanyu Li and Yichi Zhang and Speed Zhu and Hang Su and Jun Zhu and Yinpeng Dong},
      year={2026},
      eprint={2605.26177},
      archivePrefix={arXiv},
      primaryClass={cs.SE},
      url={https://arxiv.org/abs/2605.26177},
}
```
