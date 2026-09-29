# Export RepoMirage Task Datasets

These scripts convert RepoMirage task assignment JSON files into local Hugging Face dataset folders that can be read by mini-swe-agent or `datasets.load_dataset`.

The easiest way to run them is through the top-level entry point (from the repository root):

```bash
# Export all four task families using the default workspace
python cli.py export

# Or export a single task family
python cli.py export proxy_chain
```

With the default workspace, the exported layout is:

```text
repomirage_output/
  datasets/
    repomirage_multifile/
      data/test.parquet
      dataset_info.json
      repomirage_dataset_metadata.json
    repomirage_proxy_chain/
    repomirage_runtime_target/
    repomirage_missing_constant/
```

Each exported row is copied from the source SWE-bench dataset, filtered by `instance_id`, and augmented with:

- `repomirage_task_type`
- `image_name`
- `docker_image`

`image_name` and `docker_image` point to the generated task Docker image using the configured image prefix and task tag.

## Running the scripts directly

```bash
python run_extract_datasets.py \
  --input-dataset ../../SWE-bench_Verified \
  --tasks-dir ../../repomirage_output/tasks \
  --output-root ../../repomirage_output/datasets \
  --overwrite
```

You can also export one task family with `build_hf_dataset.py` directly:

```bash
python build_hf_dataset.py \
  --input-dataset ../../SWE-bench_Verified \
  --task-list-json ../../repomirage_output/tasks/proxy_top_144.json \
  --output-dir ../../repomirage_output/datasets/repomirage_proxy_chain \
  --task-type proxy_chain \
  --image-tag repomirage_proxy_chain \
  --overwrite
```
