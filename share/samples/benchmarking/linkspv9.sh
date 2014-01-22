#!/bin/bash
#
# DO NOT USE THIS SCRIPT. SEE REASONS BELOW !
#
# This script was written to reduce the space needed
# for running multiple SPECViewPerf copies.
#
# The helper script copies the SPV9 directory, each of
# which is 1.9 GB.
#
# Looking inside the source tree, I figured that 
# the mh3packed and msh3shared files were taking the
# bulk of the space.
#
# So I hit upon a plan - create a separate directory
# with these files; use links to these files in the
# original directory. When the helper file next copies
# the SPV9 directory, about 150 MB of data gets copied.
#
# However, with this scheme, some tests fail to run!
# e.g. 3dsmax returns a score of 0. I can't find the
# cause of the failure, but have decided to keep the
# script in case someone finds the reason for the
# failure
#
#
SRCDIR=$1
DSTDIR=$2

mkdir -p $DSTDIR

for srcfile in `find $SRCDIR -name "*.mh3packed"` `find $SRCDIR -name "*.msh3shared"`; do
	fname=`echo $srcfile | sed -e "s/.*\/\(.*\)/\\1/"`
	tgtfile=$DSTDIR/$fname
	echo "$srcfile -> $tgtfile"
	cp $srcfile $tgtfile
	rm $srcfile
	ln $tgtfile $srcfile
done

echo 'After linking in files, space usage is:'
du -sh $SRCDIR
du -sh $DSTDIR
