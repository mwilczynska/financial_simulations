from pathlib import Path
import re
import subprocess


root = Path(__file__).resolve().parents[1]
files = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                       cwd=root, capture_output=True, text=True, check=True).stdout.splitlines()
files = sorted(set(files))
links = 0
for filename in files:
    path = root / filename
    if path.suffix not in {".md", ".py", ".toml", ".yml", ".txt"}:
        continue
    raw = path.read_bytes()
    if b"\r\n" in raw:
        raise AssertionError(f"CRLF source/document file: {filename}")
    content = raw.decode("utf-8")
    if re.search(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]", content):
        raise AssertionError(f"Machine-specific absolute path: {filename}")
    if path.suffix == ".md":
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", content):
            if re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", target) or target.startswith("#"):
                continue
            target = target.split("#", 1)[0].strip("<>")
            if not (path.parent / target).is_file():
                raise AssertionError(f"Broken local link: {filename} -> {target}")
            links += 1
print(f"Checked {len(files)} project files, UTF-8/LF, absence of machine paths, and {links} local links.")
ignored = subprocess.run(["git", "check-ignore", "scenarios/private/example.toml", "output/example.html",
                          "data/local/example.csv", ".env"], cwd=root, capture_output=True, text=True, check=True)
if len(ignored.stdout.splitlines()) != 4:
    raise AssertionError("Private/generated paths must remain ignored.")
print("Private scenarios, outputs, local data and environment secrets remain ignored.")
