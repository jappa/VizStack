#!/bin/sh
#
# Helper script for run-specviewperf9.py
# 
# Changes to the directory of the script and
# executes Run_All
#
BASEDIR=$1
GPU=$2
NEWDIR=/tmp/SPV9-$GPU
rm -rf $NEWDIR
echo "Copying SPECViewPerf9 directory for this GPU"
cp -r $BASEDIR $NEWDIR
cd $NEWDIR 
./Run_All.csh 2>/dev/null

# Use the following lines to simulate running Run_All.csh
# This lets me test the script without waiting half an
# hour for SPECViewPerf to run !
#
# cd $BASEDIR
# cat sum_results/runallsummary.txt
