"""
Setup A100 instance for dataset downloads.
Run: python scripts/setup_a100_download.py
"""
import paramiko, time

HOST = "region-9.autodl.pro"
PORT = 49022
USER = "root"
PWD = "aVuqp5CTny/q"

def ssh_cmd(cmd, timeout=60):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode()
    err = stderr.read().decode()
    return out.strip(), err.strip()

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, port=PORT, username=USER, password=PWD, timeout=15)
print("[SSH] Connected to A100\n")

# Step 1: Check miniconda
out, err = ssh_cmd("ls /root/miniconda3/bin/python* 2>&1 | head -3")
print(f"[1] Miniconda: {out}")

# Step 2: Install via miniconda pip
setup = """
export PATH=/root/miniconda3/bin:$PATH
pip install huggingface_hub -q 2>&1 | tail -3
pip install datasets -q 2>&1 | tail -3
echo "=== VERIFY ==="
python -c "import huggingface_hub; print('hf_ok')"
python -c "import datasets; print('datasets_ok')"
echo "=== DONE ==="
"""
print("[2] Installing huggingface_hub + datasets...")
out, err = ssh_cmd(setup, timeout=180)
print(out)
if err:
    print("STDERR:", err[:300])

# Step 3: Check disk
print("\n[3] Disk status:")
out, err = ssh_cmd("df -h /root/autodl-tmp")
print(out)

# Step 4: Write download script
dl_script = '''
#!/usr/bin/env python
"""Download GarmageSet from HuggingFace."""
import os
os.environ["HF_ENDPOINT"] = "https://huggingface.co"
os.environ["HF_HOME"] = "/root/autodl-tmp/.cache"
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"

from huggingface_hub import snapshot_download, hf_hub_download
import sys

target = sys.argv[1] if len(sys.argv) > 1 else "Style3D/GarmageSet"
local_dir = sys.argv[2] if len(sys.argv) > 2 else "/root/autodl-tmp/garmageset"

print(f"Downloading {target} -> {local_dir}")
print("This may take a while (estimated 10-15 GB for raw meshes)...")

try:
    path = snapshot_download(
        repo_id=target,
        local_dir=local_dir,
        repo_type="dataset",
        resume_download=True,
        max_workers=4,
    )
    print(f"Downloaded to: {path}")
except Exception as e:
    print(f"Error: {e}")
    print("Trying individual file download instead...")
    # Fallback: download individual shards
    from huggingface_hub import list_repo_files
    files = list_repo_files(target, repo_type="dataset")
    print(f"Found {len(files)} files")
'''

script_path = "/root/autodl-tmp/download_garmageset.py"
client.exec_command(f"cat > {script_path} << 'PYEOF'\n{dl_script}\nPYEOF")
out, err = ssh_cmd(f"wc -l {script_path}")
print(f"\n[4] Download script: {out}")

# Step 5: Start download in background
print("\n[5] Starting download in background...")
out, err = ssh_cmd(
    "cd /root/autodl-tmp && "
    "export PATH=/root/miniconda3/bin:$PATH && "
    "nohup python download_garmageset.py Style3D/GarmageSet /root/autodl-tmp/garmageset "
    "> /root/autodl-tmp/download.log 2>&1 & "
    "echo PID=$!"
)
print(f"PID: {out}")

# Wait and check
time.sleep(5)
out, err = ssh_cmd("tail -10 /root/autodl-tmp/download.log 2>&1")
print(f"\n[6] Download log:\n{out}")
if err:
    print("STDERR:", err[:200])

client.close()
print("\nDone.")
