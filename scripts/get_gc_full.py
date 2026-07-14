"""Query DSpace 7 API — full item details for GarmentCodeData."""
import urllib.request, json, sys

UUID = "d9df8fe3-2add-49a2-bb58-21750ca7970c"
BASE = "https://www.research-collection.ethz.ch/server/api"

url = f"{BASE}/core/items/{UUID}"
data = json.loads(urllib.request.urlopen(url, timeout=30).read())

print("=== All _links ===")
for k, v in data.get("_links", {}).items():
    print(f"  {k}: {v.get('href', '?')}")

print("\n=== Bundles ===")
bundle_url = data.get("_links", {}).get("bundles", {}).get("href", "")
if bundle_url:
    try:
        bdata = json.loads(urllib.request.urlopen(bundle_url, timeout=30).read())
        bundles = bdata.get("_embedded", {}).get("bundles", [])
        for bundle in bundles:
            bname = bundle.get("name", "?")
            print(f"\n  Bundle: {bname}")
            # Get bitstreams for this bundle
            bs_url = bundle.get("_links", {}).get("bitstreams", {}).get("href", "")
            if bs_url:
                bsdata = json.loads(urllib.request.urlopen(bs_url, timeout=30).read())
                bitstreams = bsdata.get("_embedded", {}).get("bitstreams", [])
                for b in bitstreams:
                    name = b.get("name", "?")
                    size = b.get("sizeBytes", 0)
                    content_url = b.get("_links", {}).get("content", {}).get("href", "")
                    print(f"    {name}: {size/1024/1024:.0f} MB")
                    print(f"    -> {content_url}")
    except Exception as e:
        print(f"  Error: {e}")

print("\n=== Metadata: dc.relation / dc.identifier ===")
for key, vals in data.get("metadata", {}).items():
    if any(kw in key for kw in ["relation", "identifier", "format", "description"]):
        for v in vals[:2]:
            print(f"  {key}: {v.get('value', '?')[:200]}")

print("\n=== dc.rights / dc.type ===")
for key, vals in data.get("metadata", {}).items():
    if any(kw in key for kw in ["rights", "type", "title"]):
        for v in vals[:1]:
            print(f"  {key}: {v.get('value', '?')[:200]}")
