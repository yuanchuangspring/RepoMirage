<div align="center">
  <h1>🔮 RepoMirage</h1>
  <p><em>Measuring Repository Context Reasoning Beyond Issue Resolution.</em></p>
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

* **[Accepted]** RepoMirage has been accepted by **NeurIPS 2026 ED Track**! 🔥

## 👋 Overview

RepoMirage is a benchmark-construction toolkit for measuring **repository-context reasoning** in code agents: the ability to trace cross-file structure, hidden runtime targets, proxy imports, and externalized constants. It has two complementary stages:

1. **RepoMirage-Perturb** — applies *semantics-preserving repository perturbations* to issue-resolution instances. The issue, the gold patch, and the tests stay untouched; the repository structure becomes harder to reason about.
2. **RepoMirage-Extend** — turns the structural bottlenecks introduced by perturbation into four explicit, automatically checkable task families.

## 🚀 Quick Start

> [!NOTE]
> RepoMirage works with **any SWE-bench-format dataset** — including new datasets you build with [SWE-smith](https://github.com/SWE-bench/SWE-smith). The setup below uses the official SWE-bench (Verified) as the running example.

**0. Docker.** SWE-bench-format images are large — use an `x86_64` machine with at least ~120 GB of free disk. Install Docker and make sure your user can run it (Linux: [post-install steps](https://docs.docker.com/engine/install/linux-postinstall/)).

**1. Clone this repository and install the host packages.**

```bash
git clone https://github.com/yuanchuangspring/RepoMirage.git
cd RepoMirage
pip install -r requirements.txt
```

**2. Get a dataset.** As the running example, download SWE-bench (Verified) into the default location, `./SWE-bench_Verified`:

```python
from datasets import load_dataset
load_dataset("SWE-bench/SWE-bench_Verified", split="test").save_to_disk("SWE-bench_Verified")
```

> [!NOTE]
> Any SWE-bench-format dataset works the same way — Verified, Lite, the full set, or a SWE-smith-generated dataset. Point `--dataset-dir` at it (a local directory or a Hugging Face dataset id).

**3. Prepare the offline `libcst` wheel.** The perturbation runs inside containers with no network access, so a `libcst` wheel must be bundled locally:

```bash
mkdir -p RepoMirage_Perturb/wheels
pip download libcst --no-deps -d RepoMirage_Perturb/wheels
```

**4. Base Docker images.** (Optional) RepoMirage pulls the base image of each instance on demand (e.g. `swebench/sweb.eval.x86_64.django_1776_django-10914:latest` for the SWE-bench example). You can pre-warm them to avoid waiting during the run:

```bash
docker pull swebench/sweb.eval.x86_64.django_1776_django-10914:latest   # example instance
```

**5. Run the pipeline.** From the repository root:

```bash
# ① Build perturbed repositories (metadata is exported automatically)
python cli.py perturb

# ② Assign tasks and build task images
python cli.py extend

# ③ (optional) Export task datasets for agent runners
python cli.py export
```

**Test your installation** by building a single perturbed image first:

```bash
python cli.py perturb --limit 1
```

If it succeeds you get the image `swebench/sweb.eval.x86_64.<instance_id>:repomirage` plus `repomirage_output/metadata/<instance_id>.json`.

> [!TIP]
> * **Smoke test**: `python cli.py perturb --limit 3`
> * **No-Docker dry run**: `python cli.py extend summary` only writes the task lists
> * **Work on a subset**: `python cli.py perturb --instance-regex 'django__'`
> * **Move all artifacts**: set the `REPOMIRAGE_OUT` environment variable
> * Every subcommand has `--help`; see [Common Options](#-common-options)

## 💽 Usage

* **① perturb** — for each instance, starts its base image, applies the perturbation modules to the files touched by the gold patch, exports metadata, removes it from the image, rebuilds the git history, and commits the tag `repomirage`.
* **② extend** — `summary` first groups instances into four task families from the metadata; then `proxy` / `runtime` / `constant` build the task-specific images.
* **③ export** — writes one Hugging Face-style dataset per task family, each row carrying `repomirage_task_type`, `image_name`, and `docker_image` columns so your runner picks the right image.

## 📂 What Gets Generated

```text
repomirage_output/
├── built_instances.json              # instances whose perturbed images were built
├── metadata/<instance_id>.json       # what was perturbed per instance (bridge ① → ②)
├── tasks/
│   ├── proxy_top_144.json            # → Proxy Chain Completion
│   ├── constant_top_144.json         # → Missing Constant Recovery
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

## 🧩 Task Families

| Family | Selection | Agent task |
|---|---|---|
| **Multi-File Issue Resolution** | gold patch touches > 1 file | solve the original issue on the perturbed repo |
| **Proxy Chain Completion** | top-K by proxy count | reconstruct erased middle-layer proxy files |
| **Runtime Target Identification** | remaining instances | find the real implementation among decoys |
| **Missing Constant Recovery** | top-K by extracted constants | recover removed JSON keys while preserving values |

Perturbation modules behind all of this (all enabled by default, `--only` to select):

* `proxy_import` — rewrites direct imports through multi-hop proxy files
* `in_place_hiding` — hides the real implementation behind a wrapper package
* `fake_files` — adds decoy files that look like the real implementation
* `dynamic_dependency` — moves constants out of code into JSON resources

## ✅ Validating Agent Runs

```bash
python cli.py validate proxy    solutions.json repomirage_output/tasks/proxy_chain_generation_summary.json
python cli.py validate runtime  solutions.json repomirage_output/tasks/runtime_target_generation_summary.json
python cli.py validate constant solutions.json repomirage_output/tasks/missing_constant_generation_summary.json
```

`solutions.json` is a list of `{instance_id, patch}` objects or a dict keyed by `instance_id`; the patch field may be named `patch`, `agent_patch`, `completion_patch`, or `model_patch`. Reports go to `repomirage_output/reports/`.

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

The individual scripts still run standalone with the same defaults, and legacy option names (e.g. `--host-metadata-dir`, `--yes-con-output`) remain accepted as aliases.

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
