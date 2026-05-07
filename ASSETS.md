# Licenses and Terms

The RepoMirage source code is released under the MIT License, as specified in the root `LICENSE` file.

## External assets

| Asset | Usage in RepoMirage | License |
|---|---|---|
| SWE-Bench / SWE-Bench Verified | Source benchmark and Docker-compatible repository environments | MIT |
| mini-swe-agent | Agent execution framework under the standard bash-only setting | MIT |
| LibCST | Python syntax-tree transformation for perturbation construction | MIT |

## SWE-Bench repositories and Docker environments

RepoMirage builds on SWE-Bench Verified. We do not redistribute original SWE-Bench repositories, modified repositories, original Docker images, or modified Docker images. Users should obtain SWE-Bench Verified resources from the official SWE-Bench distribution channels.

Generated perturbed repositories and task environments are constructed locally from user-prepared SWE-Bench-compatible environments. These generated outputs remain subject to the licenses and terms of the corresponding original repositories and benchmark resources.

## Model providers

RepoMirage may evaluate agents instantiated with proprietary API models or open-weight models. This repository does not redistribute model weights, API outputs, or provider-specific artifacts. Users are responsible for complying with the terms of the corresponding model providers or model releases.

## Python dependencies

Additional Python dependencies used by the released scripts remain under their respective licenses. Users should consult the package metadata of each dependency for detailed license information.
