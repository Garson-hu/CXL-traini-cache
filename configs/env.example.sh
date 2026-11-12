# Example shell environment for the CXL training data cache project.
#
# Usage (nothing here is applied automatically):
#   cp configs/env.example.sh configs/env.local.sh   # env.local.sh is git-ignored
#   source configs/env.local.sh
#
# This file only exports variables. It does not create directories and it does
# not touch ~/.bashrc, ~/.profile, or any other shell startup file.
# Background and rationale: docs/storage.md

# --- Required ----------------------------------------------------------------
# Root for all large project data (workloads, datasets, checkpoints, traces,
# raw results, temporary files). Scripts must read this variable instead of
# hardcoding a storage path.
export CXL_TRAINING_DATA_ROOT=/mnt/beegfs/ghu4/cxl-train-cache

# --- Optional: keep temporary files, caches, and builds out of $HOME ----------
# Uncomment what you need. All targets are under $CXL_TRAINING_DATA_ROOT so they
# do not count against the 40 GB home quota. Create a directory before pointing
# a tool at it (for example: mkdir -p "$CXL_TRAINING_DATA_ROOT/tmp/pip-cache").

# Temporary files of training runs and benchmarks.
# export TMPDIR="$CXL_TRAINING_DATA_ROOT/tmp"

# Python package caches.
# export PIP_CACHE_DIR="$CXL_TRAINING_DATA_ROOT/tmp/pip-cache"
# export CONDA_PKGS_DIRS="$CXL_TRAINING_DATA_ROOT/tmp/conda-pkgs"

# Framework and dataset download caches.
# export XDG_CACHE_HOME="$CXL_TRAINING_DATA_ROOT/tmp/xdg-cache"
# export TORCH_HOME="$CXL_TRAINING_DATA_ROOT/tmp/torch-cache"
# export KERAS_HOME="$CXL_TRAINING_DATA_ROOT/tmp/keras-cache"
# export TFDS_DATA_DIR="$CXL_TRAINING_DATA_ROOT/datasets/tfds"
# export HF_HOME="$CXL_TRAINING_DATA_ROOT/tmp/hf-cache"

# Large out-of-tree build directory (for example: cmake -B "$CXL_BUILD_DIR/<name>").
# export CXL_BUILD_DIR="$CXL_TRAINING_DATA_ROOT/tmp/build"
