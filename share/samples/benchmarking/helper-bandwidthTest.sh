#!/bin/bash

#
# Helper script for run-cudabandwidth-all-gpus.py
#
# Uses GPU_INDEX as the CUDA device to run the test on!
#
export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/local/cuda/lib64
APPPATH=$1/C/bin/linux/release
shift
ARGS=$*

# Run bandwidthTest
echo | $APPPATH/bandwidthTest --device=$GPU_INDEX $ARGS
