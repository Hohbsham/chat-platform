#!/bin/bash
# Download GarmageSet raw shards from hf-mirror
MIRROR="https://hf-mirror.com"
REPO="Style3D/GarmageSet"
DL_DIR="/root/autodl-tmp/garmageset_raw"
mkdir -p "$DL_DIR"

# Download raw shards (00-255, ~200MB each)
# Start with batch 00-09 as test
for i in 00 01 02 03 04 05 06 07 08 09; do
    FILE="raw/raw_${i}.tar.gz"
    URL="${MIRROR}/${REPO}/resolve/main/${FILE}"
    echo "[$(date +%H:%M:%S)] Downloading $FILE..."
    wget -q --show-progress -c "$URL" -P "$DL_DIR" 2>&1 || echo "FAILED: $FILE"
done

echo "Done. Files:"
ls -lh "$DL_DIR/"
df -h /root/autodl-tmp
