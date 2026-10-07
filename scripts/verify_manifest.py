from pathlib import Path
import hashlib,json
root=Path(__file__).resolve().parents[1]
manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
for rel,digest in manifest['sha256'].items():
    path=root/rel
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
        raise SystemExit('Hash mismatch: '+rel)
print('Verified:',len(manifest['sha256']),'files; version:',manifest['package_version'])
