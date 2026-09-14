"""Package the delivered plugin without development caches."""
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

root = Path(__file__).resolve().parent
source = root / "quota-resume"
manifest = json.loads((source / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
destination = root / "dist" / f"{manifest['name']}-{manifest['version']}.zip"
destination.parent.mkdir(exist_ok=True)
files = sorted(p for p in source.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
    for path in files:
        archive.write(path, path.relative_to(root).as_posix())
with ZipFile(destination) as archive:
    assert archive.testzip() is None
    assert "quota-resume/.codex-plugin/plugin.json" in archive.namelist()
    assert "quota-resume/skills/quota-resume/SKILL.md" in archive.namelist()
print(json.dumps({"zip": str(destination), "files": len(files), "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()}, ensure_ascii=True))
