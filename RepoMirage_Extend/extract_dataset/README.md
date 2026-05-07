# Extract RepoMirage Task Datasets

These scripts convert RepoMirage task assignment JSON files into local Hugging Face dataset folders that can be read by mini-swe-agent or `datasets.load_dataset`.

Typical workflow:

```bash
python run_extract_datasets.py \
  --input-dataset ../../SWE-bench_Verified \
  --stats-dir ../../repomirage_metadata_stats \
  --output-root ../../repomirage_hf_datasets \
  --overwrite
```

The output layout is:

```text
repomirage_hf_datasets/
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

You can export one task family directly:

```bash
python build_hf_dataset.py \
  --input-dataset ../../SWE-bench_Verified \
  --task-list-json ../../repomirage_metadata_stats/proxy_top_144.json \
  --output-dir ../../repomirage_hf_datasets/repomirage_proxy_chain \
  --task-type proxy_chain \
  --image-tag repomirage_proxy_chain \
  --overwrite
```
