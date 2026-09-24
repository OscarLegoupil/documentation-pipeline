"""Development-only local LibreOffice administrative extraction (Windows)."""
from pathlib import Path
import hashlib
import subprocess
import urllib.request

root = Path(__file__).resolve().parents[1] / ".tools"
url = "https://download.documentfoundation.org/libreoffice/stable/25.8.7/win/x86_64/LibreOffice_25.8.7_Win_x86-64.msi"
msi = root / "libreoffice.msi"
if not msi.exists():
    urllib.request.urlretrieve(url, msi)
expected = urllib.request.urlopen(url + ".sha256", timeout=30).read().decode().split()[0]
actual = hashlib.sha256(msi.read_bytes()).hexdigest()
if actual != expected:
    raise ValueError("LibreOffice download checksum mismatch")
print("Verified LibreOffice 25.8.7 SHA256", actual, flush=True)
result = subprocess.run(["msiexec.exe", "/a", str(msi), "/qn", "TARGETDIR=" + str(root / "libreoffice"), "/L*v", str(root / "libreoffice-extract.log")], check=True, timeout=240)
print("Extracted local LibreOffice files", flush=True)
