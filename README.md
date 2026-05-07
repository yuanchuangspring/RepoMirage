# RepoMirage Benchmark Toolkit

RepoMirage is a benchmark-generation and evaluation toolkit for probing repository-context reasoning in code agents. It builds on SWE-bench-style repository environments and introduces controlled repository-level perturbations that preserve task semantics while increasing the need to trace cross-file structure, runtime targets, proxy imports, and externalized constants.

The toolkit supports two complementary stages:

1. **RepoMirage-Perturb** applies semantics-preserving repository transformations to existing benchmark instances while keeping the original issue-resolution objective and evaluation protocol.
2. **RepoMirage-Extend** turns the structural bottlenecks introduced by perturbation into explicit benchmark tasks, making repository-context reasoning easier to measure directly.

This repository is released as an executable benchmark-construction toolkit rather than a static dataset. It does not redistribute modified benchmark repositories or Docker images. Instead, it reconstructs perturbed repositories and derived task environments from existing SWE-bench-compatible Docker images.

## Repository Structure

```text
.
├── RepoMirage_Perturb/        # Build perturbed repository images and export metadata
├── RepoMirage_Extend/         # Generate derived task images and validation scripts
├── repomirage_metadata/       # Exported per-instance perturbation metadata
├── repomirage_metadata_stats/ # Task assignment files and generation summaries
└── repomirage_hf_datasets/    # Optional local Hugging Face-style datasets
```

The two main components are:

* `RepoMirage_Perturb/`: constructs RepoMirage-perturbed SWE-bench Docker images and exports per-instance metadata.
* `RepoMirage_Extend/`: uses the exported metadata to assign instances to task families and generate task-specific Docker images.

## Requirements

Before running the toolkit, make sure the following dependencies are available:

* Docker is running and accessible from the current user.
* SWE-bench-compatible base Docker images have been prepared.
* Host Python packages:

  * `docker`
  * `datasets`
  * `tqdm`
* `RepoMirage_Perturb/` also expects a local `wheels/` directory containing an installable `libcst` wheel and any required offline dependencies.

## Quick Start

The full workflow has three steps:

1. Build perturbed repository images with `RepoMirage_Perturb`.
2. Generate derived task images with `RepoMirage_Extend`.
3. Optionally export task lists into local Hugging Face-style datasets for agent runners.

```bash
# Step 1: generate perturbed repositories and metadata
cd RepoMirage_Perturb
python repomirage.py \
  --dataset-dir SWE-bench_Verified \
  --split test \
  --wheels-dir wheels \
  --aug-tag repomirage \
  --host-metadata-dir ../repomirage_metadata \
  --yes-con-output ../yes_con.json

# Step 2: generate task assignments and task-specific images
cd ../RepoMirage_Extend
python run_extend_workflow.py \
  --metadata-dir ../repomirage_metadata \
  --output-dir ../repomirage_metadata_stats \
  --source-tag repomirage

# Step 3: optionally extract local datasets for mini-swe-agent-style runners
cd extract_dataset
python run_extract_datasets.py \
  --input-dataset ../../SWE-bench_Verified \
  --stats-dir ../../repomirage_metadata_stats \
  --output-root ../../repomirage_hf_datasets \
  --overwrite
```

## Part 1: RepoMirage-Perturb

`RepoMirage_Perturb/repomirage.py` loads SWE-bench instances, starts the corresponding base Docker images, applies repository-level perturbations inside each container, exports per-instance metadata, removes metadata from the committed image, and writes a list of successfully constructed instances.

```bash
cd RepoMirage_Perturb
python repomirage.py \
  --dataset-dir SWE-bench_Verified \
  --split test \
  --wheels-dir wheels \
  --aug-tag repomirage \
  --host-metadata-dir ../repomirage_metadata \
  --yes-con-output ../yes_con.json
```

### Perturbation Modules

RepoMirage-Perturb currently supports four construction modules:

* `proxy_import`: rewrites direct imports through multi-hop proxy files, making dependency paths less locally visible.
* `in_place_hiding`: masks the original runtime target behind a wrapper package and renamed implementation file.
* `fake_files`: adds nearby decoy files that are superficially similar to the real runtime file but differ in behaviorally meaningful details.
* `dynamic_dependency`: externalizes local constant values into JSON resources loaded at runtime.

If `--only` is omitted, all perturbation modules are enabled.

### Useful Options

```bash
--dataset-dir PATH_OR_DATASET   Dataset path/name passed to datasets.load_dataset.
--split SPLIT                   Dataset split. Default: test.
--aug-tag TAG                   Docker tag for transformed images. Default: repomirage.
--wheels-dir PATH               Local offline wheel directory. Default: wheels.
--metadata-subdir PATH          In-container metadata path under /testbed.
--host-metadata-dir PATH        Host directory for exported metadata JSON files.
--yes-con-output PATH           JSON file listing successfully committed instances.
--instance-regex REGEX          Only process matching instance IDs.
--limit N                       Stop after N processed matching instances.
--force                         Rebuild even if the target Docker tag already exists.
--only NAME [NAME ...]          Enable only selected perturbation modules.
```

## Part 2: RepoMirage-Extend

`RepoMirage_Extend/summary.py` reads the metadata exported by RepoMirage-Perturb and assigns instances to four benchmark task families.

### Task Families

* **Multi-File Issue Resolution**: retains issue-resolution instances whose gold patches modify more than one file.
* **Proxy Chain Completion**: erases intermediate proxy files and requires agents to reconstruct the missing dependency-routing logic.
* **Runtime Target Identification**: removes the wrapper reference to the real runtime file and requires agents to distinguish the true implementation from decoys.
* **Missing Constant Recovery**: removes selected JSON keys while preserving values, requiring agents to recover cross-file key-value associations.

The assignment outputs include:

* `touched_files_gt1_<N>.json` for Multi-File Issue Resolution.
* `proxy_top_<K>.json` for Proxy Chain Completion.
* `constant_top_<K>.json` for Missing Constant Recovery.
* `remainder.json` for Runtime Target Identification.

### One-Click Workflow

The one-click workflow runs task assignment and then generates task-specific Docker images for Proxy Chain Completion, Runtime Target Identification, and Missing Constant Recovery.

```bash
cd RepoMirage_Extend
python run_extend_workflow.py \
  --metadata-dir ../repomirage_metadata \
  --output-dir ../repomirage_metadata_stats \
  --source-tag repomirage
```

By default, the workflow runs:

```text
summary proxy runtime constant
```

To only produce task assignment files:

```bash
python run_extend_workflow.py \
  --metadata-dir ../repomirage_metadata \
  --output-dir ../repomirage_metadata_stats \
  --steps summary
```

### Common Extend Options

```bash
--proxy-top-k N             Number of Proxy Chain instances. Default: 144.
--constant-top-k N          Number of Missing Constant instances. Default: 144.
--source-tag TAG            Docker source tag from Part 1. Default: repomirage.
--proxy-target-tag TAG      Docker target tag for Proxy Chain images.
--runtime-target-tag TAG    Docker target tag for Runtime Target images.
--constant-target-tag TAG   Docker target tag for Missing Constant images.
--seed N                    Random seed for deterministic instance edits.
--overwrite                 Rebuild target images even if the tag already exists.
--git-user-name NAME        Git author name used in generated image commits.
--git-user-email EMAIL      Git author email used in generated image commits.
```

### Running Generators Directly

Each Extend generator can also be run directly:

```bash
python summary.py \
  --metadata-dir ../repomirage_metadata \
  --output-dir ../repomirage_metadata_stats

python ProxyChain.py \
  --proxy-top-json ../repomirage_metadata_stats/proxy_top_144.json \
  --metadata-dir ../repomirage_metadata \
  --source-tag repomirage

python RuntimeTarget.py \
  --instances-json ../repomirage_metadata_stats/remainder.json \
  --metadata-dir ../repomirage_metadata \
  --source-tag repomirage

python MissingConstant.py \
  --instances-json ../repomirage_metadata_stats/constant_top_144.json \
  --metadata-dir ../repomirage_metadata \
  --source-tag repomirage
```

## Validation Helpers

`RepoMirage_Extend/` includes validators for agent-submitted repair patches:

```bash
python validate_ProxyChain.py solutions.json proxy_chain_generation_summary.json \
  --metadata-dir ../repomirage_metadata

python validate_RuntimeTarget.py solutions.json runtime_target_generation_summary.json

python validate_MissingConstant.py solutions.json missing_constant_generation_summary.json
```

`solutions.json` can be either:

* a list of solution objects, or
* an object keyed by `instance_id`.

Each solution entry should include a patch field such as:

* `patch`
* `agent_patch`
* `completion_patch`
* `model_patch`

## Dataset Extraction

`RepoMirage_Extend/extract_dataset/` converts generated task lists into local Hugging Face-style dataset folders for mini-swe-agent-style runners.

```bash
cd RepoMirage_Extend/extract_dataset
python run_extract_datasets.py \
  --input-dataset ../../SWE-bench_Verified \
  --stats-dir ../../repomirage_metadata_stats \
  --output-root ../../repomirage_hf_datasets \
  --overwrite
```

This writes one dataset per task family and adds the following columns:

* `repomirage_task_type`
* `image_name`
* `docker_image`

These fields allow downstream runners to select the generated task image for each instance.

## Output Artifacts

After running the full workflow, the main generated artifacts are:

```text
repomirage_metadata/          # Per-instance perturbation metadata
repomirage_metadata_stats/    # Task assignment files and generation summaries
repomirage_hf_datasets/       # Optional local datasets for agent runners
Docker images                 # Perturbed and task-specific repository environments
```

The generated Docker images are tagged according to the source and target tags provided in the command-line options.

## Reproducibility Notes

* RepoMirage operates on existing SWE-bench-compatible Docker environments.
* The toolkit reconstructs perturbed repositories and derived tasks through deterministic scripts.
* Metadata exported during perturbation is used as the bridge between RepoMirage-Perturb and RepoMirage-Extend.
* Derived tasks are designed to be automatically checkable by deterministic validation scripts.
* For repeatable construction, use a fixed `--seed` when generating Extend tasks.

## Anonymity and Asset Policy

This repository is intended for anonymous review. It does not include author names, affiliation information, or venue-specific identifiers. It also does not redistribute modified copies of upstream benchmark repositories or Docker images. Users should prepare the original SWE-bench-compatible resources through their official distribution channels and run the provided scripts to reconstruct the benchmark environments locally.

## Troubleshooting

**Docker permission error**

Make sure Docker is running and that the current user has permission to access the Docker daemon.

**Missing `libcst` or offline dependency errors**

Check that `RepoMirage_Perturb/wheels/` contains an installable `libcst` wheel and any required offline dependencies.

**No instances are processed**

Verify that `--dataset-dir`, `--split`, and `--instance-regex` match the intended SWE-bench-compatible instance IDs.

**Generated image already exists**

Use `--force` in RepoMirage-Perturb or `--overwrite` in RepoMirage-Extend to rebuild existing images.

**Validator cannot find a patch field**

Ensure that each solution entry contains one of the supported patch fields: `patch`, `agent_patch`, `com

