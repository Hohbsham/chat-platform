#!/bin/bash
# Find GarmentCodeData download URLs on ETH Research Collection
set -e

echo "=== Following DOI redirect ==="
curl -sL --connect-timeout 15 "https://doi.org/10.3929/ethz-b-000673889" -o /tmp/eth_page1.html
echo "Page 1: $(wc -c < /tmp/eth_page1.html) bytes"

echo ""
echo "=== Getting final landing page ==="
FINAL_URL=$(curl -sL --connect-timeout 15 -w "%{url_effective}" -o /tmp/eth_final.html "https://doi.org/10.3929/ethz-b-000673889")
echo "Final URL: $FINAL_URL"

echo ""
echo "=== Searching for download links ==="
grep -i "bitstream\|download\|\.tar\|\.zip" /tmp/eth_final.html | head -20 || echo "No direct links found"

echo ""
echo "=== All links ==="
grep -oP 'href="[^"]*"' /tmp/eth_final.html | grep -i "bitstream\|download\|\.tar\|\.zip\|\.gz" | head -20

echo ""
echo "=== Page title ==="
grep -oP '<title>[^<]*</title>' /tmp/eth_final.html || echo "no title"

echo ""
echo "=== Full page sample ==="
head -100 /tmp/eth_final.html
