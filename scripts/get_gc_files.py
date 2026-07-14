"""Query DSpace 7 API for GarmentCodeData bitstreams."""
import urllib.request, json

UUID = "d9df8fe3-2add-49a2-bb58-21750ca7970c"
BASE = "https://www.research-collection.ethz.ch/server/api"

# Get item details
print("=== Item Metadata ===")
url = f"{BASE}/core/items/{UUID}"
data = json.loads(urllib.request.urlopen(url, timeout=30).read())
print(f"Name: {data.get('name')}")
print(f"Handle: {data.get('handle')}")
print(f"Type: {data.get('entityType')}")

# Get bitstreams
print("\n=== Bitstreams (Downloadable Files) ===")
url2 = f"{BASE}/core/items/{UUID}/bitstreams"
data2 = json.loads(urllib.request.urlopen(url2, timeout=30).read())
bitstreams = data2.get("_embedded", {}).get("bitstreams", [])
print(f"Total: {len(bitstreams)} files")

total_size = 0
for b in bitstreams:
    name = b.get("name", "?")
    size = b.get("sizeBytes", 0)
    total_size += size
    link = b.get("_links", {}).get("content", {}).get("href", "")
    print(f"\n  {name}")
    print(f"  Size: {size/1024/1024:.0f} MB")
    print(f"  URL: {link}")

print(f"\n=== Total: {total_size/1024/1024/1024:.1f} GB ===")
