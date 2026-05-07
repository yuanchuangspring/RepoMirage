# RepoMirage Benchmark Toolkit

This folder contains the submission-ready RepoMirage toolkit. It is split into two parts:

- `RepoMirage_Perturb/`: builds RepoMirage-perturbed SWE-bench Docker images and exports per-instance metadata.
- `RepoMirage_Extend/`: uses that metadata to assign instances to benchmark tasks and generate task-specific Docker images.

## Requirements

- Docker must be running and accessible from the current user.
- Host Python packages:
  - `docker`
  - `datasets`
  - `tqdm`
- `RepoMirage_Perturb` also expects a local `wheels/` directory containing an installable `libcst` wheel and required offline dependencies.

## Part 1: RepoMirage Perturb

`RepoMirage_Perturb/repomirage.py` loads SWE-bench instances, starts their base Docker images, applies the RepoMirage transformation inside each container, exports metadata, removes metadata from the committed image, and writes a success list.

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

Useful options:

```bash
--dataset-dir PATH_OR_DATASET   Dataset path/name passed to datasets.load_dataset.
--split SPLIT                  Dataset split. Default: test.
--aug-tag TAG                  Docker tag for transformed images. Default: repomirage.
--wheels-dir PATH              Local offline wheel directory. Default: wheels.
--metadata-subdir PATH         In-container metadata path under /testbed.
--host-metadata-dir PATH       Host directory for exported metadata JSON files.
--yes-con-output PATH          JSON file listing successfully committed instances.
--instance-regex REGEX         Only process matching instance IDs.
--limit N                      Stop after N processed matching instances.
--force                        Rebuild even if the target Docker tag already exists.
--only NAME [NAME ...]         Enable only selected perturbation modules.
```

Available perturbation modules are `dynamic_dependency`, `proxy_import`, `fake_files`, and `in_place_hiding`. If `--only` is omitted, all modules are enabled.

## Part 2: RepoMirage Extend

`RepoMirage_Extend/summary.py` reads the metadata exported by Part 1 and assigns instances to four benchmark task families:

- Multi-file: `touched_file_count > 1`; written as `touched_files_gt1_<N>.json`.
- Proxy Chain: top-k instances by proxy count; written as `proxy_top_<K>.json`.
- Missing Constant: top-k instances by extracted constant count; written as `constant_top_<K>.json`.
- Fake File / Runtime Target: remaining instances; written as `remainder.json`.

The one-click workflow runs task assignment and then generates the task-specific Docker images for Proxy Chain, Fake File / Runtime Target, and Missing Constant.

```bash
cd RepoMirage_Extend
python run_extend_workflow.py \
  --metadata-dir ../repomirage_metadata \
  --output-dir ../repomirage_metadata_stats \
  --source-tag repomirage
```

By default, the workflow runs `summary proxy runtime constant`. To only produce task assignment files:

```bash
python run_extend_workflow.py \
  --metadata-dir ../repomirage_metadata \
  --output-dir ../repomirage_metadata_stats \
  --steps summary
```

Common Extend options:

```bash
--proxy-top-k N             Number of Proxy Chain instances. Default: 144.
--constant-top-k N          Number of Missing Constant instances. Default: 144.
--source-tag TAG            Docker source tag from Part 1. Default: repomirage.
--proxy-target-tag TAG      Docker target tag for Proxy Chain images.
--runtime-target-tag TAG    Docker target tag for Fake File / Runtime Target images.
--constant-target-tag TAG   Docker target tag for Missing Constant images.
--seed N                    Random seed for deterministic instance edits.
--overwrite                 Rebuild target images even if the tag already exists.
--git-user-name NAME        Git author name used in generated image commits.
--git-user-email EMAIL      Git author email used in generated image commits.
```

Each generator can also be run directly:

```bash
python summary.py --metadata-dir ../repomirage_metadata --output-dir ../repomirage_metadata_stats
python ProxyChain.py --proxy-top-json ../repomirage_metadata_stats/proxy_top_144.json --metadata-dir ../repomirage_metadata --source-tag repomirage
python RuntimeTarget.py --instances-json ../repomirage_metadata_stats/remainder.json --metadata-dir ../repomirage_metadata --source-tag repomirage
python MissingConstant.py --instances-json ../repomirage_metadata_stats/constant_top_144.json --metadata-dir ../repomirage_metadata --source-tag repomirage
```

## Validation Helpers

The Extend folder includes validators for agent-submitted repair patches:

```bash
python validate_ProxyChain.py solutions.json proxy_chain_generation_summary.json --metadata-dir ../repomirage_metadata
python validate_RuntimeTarget.py solutions.json runtime_target_generation_summary.json
python validate_MissingConstant.py solutions.json missing_constant_generation_summary.json
```

`solutions.json` can be either a list of objects or an object keyed by `instance_id`. Each solution entry should include a patch field such as `patch`, `agent_patch`, `completion_patch`, or `model_patch`.

## Dataset Extraction

`RepoMirage_Extend/extract_dataset/` converts generated task lists into local Hugging Face dataset folders for mini-swe-agent-style runners.

```bash
cd RepoMirage_Extend/extract_dataset
python run_extract_datasets.py \
  --input-dataset ../../SWE-bench_Verified \
  --stats-dir ../../repomirage_metadata_stats \
  --output-root ../../repomirage_hf_datasets \
  --overwrite
```

This writes one dataset per task family and adds `repomirage_task_type`, `image_name`, and `docker_image` columns so runners can select the generated task image.
