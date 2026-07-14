#!/bin/bash
# Fetch ETH Research Collection page for GarmentCodeData
URL="https://www.research-collection.ethz.ch/handle/20.500.11850/673889"

echo "=== Fetching page ==="
curl -sL --connect-timeout 30 "$URL" -o /tmp/eth_page.html
echo "Size: $(wc -c < /tmp/eth_page.html) bytes"

echo ""
echo "=== Download/bitstream/libdrive links ==="
grep -oP 'href="[^"]*"' /tmp/eth_page.html | grep -iE "download|bitstream|libdrive|\.tar|\.zip" | head -20

echo ""
echo "=== All hrefs to external resources ==="
grep -oP 'href="https?://[^"]*"' /tmp/eth_page.html | head -30

echo ""
echo "=== JSON-LD / schema.org metadata ==="
grep -oP '<script[^>]*type="application/ld\+json"[^>]*>.*?</script>' /tmp/eth_page.html | head -5

echo ""
echo "=== Search page text for libdrive ==="
grep -i "libdrive\|download all\|tar.gz\|zip file\|bitstream" /tmp/eth_page.html | head -10

echo ""
echo "=== Page title ==="
grep -oP '<title>[^<]*</title>' /tmp/eth_page.html
