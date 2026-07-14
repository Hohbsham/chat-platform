#!/bin/bash
# Probe DSpace 7 REST API for GarmentCodeData
BASE="https://www.research-collection.ethz.ch/server"
HANDLE="20.500.11850/673889"

echo "=== 1. Try find-by-handle ==="
curl -s --connect-timeout 15 "${BASE}/api/core/items/find-by-handle?handle=${HANDLE}" 2>&1 | head -200

echo ""
echo "=== 2. Try /api/core/bitstreams search ==="
curl -s --connect-timeout 15 "${BASE}/api/discover/search/objects?query=GarmentCodeData&size=5" 2>&1 | head -200

echo ""
echo "=== 3. Try direct handle endpoint ==="
curl -s --connect-timeout 15 "${BASE}/api/handle/${HANDLE}" 2>&1 | head -200

echo ""
echo "=== 4. Try the OAI-PMH endpoint ==="
curl -s --connect-timeout 15 "https://www.research-collection.ethz.ch/server/oai?verb=GetRecord&metadataPrefix=oai_dc&identifier=oai:research-collection.ethz.ch:20.500.11850/673889" 2>&1 | head -100

echo ""
echo "=== 5. Scrape page for UUID patterns ==="
UUID=$(curl -sL --connect-timeout 15 "https://www.research-collection.ethz.ch/handle/20.500.11850/673889" 2>&1 | grep -oP '[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}' | head -5)
echo "UUIDs found: $UUID"

echo ""
echo "=== 6. Try REST with extracted UUID ==="
for uuid in $UUID; do
    echo "Trying UUID: $uuid"
    curl -s --connect-timeout 15 "${BASE}/api/core/items/${uuid}" 2>&1 | python3 -c "import json,sys; d=json.load(sys.stdin); print(json.dumps(d, indent=2)[:500])" 2>/dev/null || echo "  failed"
done
