#!/bin/bash
# GarmageSet downloader — curl with resume, no timeout
TOKEN="${HF_TOKEN}"
BASE="https://huggingface.co/datasets/Style3D/GarmageSet/resolve/main"
DL="D:/ClothesNetData/garmageset_download"
PROXY="http://127.0.0.1:7897"

mkdir -p "$DL"
OK=0; SKIP=0; FAIL=0

for i in $(seq 0 255); do
    name=$(printf "%02x" $i)
    out="$DL/raw_${name}.tar.gz"
    url="${BASE}/raw/${name}.tar.gz"

    # Check if complete (>50KB)
    if [ -f "$out" ]; then
        size=$(stat -c%s "$out" 2>/dev/null || echo 0)
        if [ "$size" -gt 50000 ]; then
            SKIP=$((SKIP + 1))
            if [ $((SKIP % 20)) -eq 0 ]; then
                echo "[$((i+1))/256] $(printf '%02x' $i): cached ($((size/1024/1024))MB) [$SKIP cached, $OK new, $FAIL fail]"
            fi
            continue
        fi
    fi

    echo "[$((i+1))/256] $(printf '%02x' $i): downloading..."
    if curl -x "$PROXY" -L -C - \
        -H "Authorization: Bearer $TOKEN" \
        -o "$out" \
        --connect-timeout 30 \
        --max-time 0 \
        --retry 3 \
        --retry-delay 10 \
        "$url" -w " -> HTTP %{http_code}, %{size_download} bytes, %{time_total}s\n" 2>&1; then
        OK=$((OK + 1))
    else
        FAIL=$((FAIL + 1))
        echo " -> FAILED"
    fi

    total=$(du -sm "$DL" 2>/dev/null | cut -f1)
    echo "  [$((i+1))/256] progress: $OK new, $SKIP cached, $FAIL fail, ${total}MB disk"
done

total=$(du -sm "$DL" | cut -f1)
echo "DONE: $OK new, $SKIP cached, $FAIL fail, ${total}MB total"
