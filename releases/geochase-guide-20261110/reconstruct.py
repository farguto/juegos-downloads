"""Reconstruct the pinned GeoChase ZIP; publishing is performed only by the gated workflow."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import urllib.request
import zipfile

REPOSITORY = "farguto/juegos-downloads"
TAG = "geochase-guide-20261110"

def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def require_file(path, expected):
    path = Path(path)
    if not path.is_file() or path.stat().st_size != expected["bytes"] or digest(path) != expected["sha256"]:
        raise ValueError("File identity mismatch: " + path.name)

def require_publication(manifest):
    publication = manifest.get("publication", {})
    if publication.get("user_requested_publication") is True:
        if publication.get("archiveSha256") != manifest["archive"]["sha256"] or not publication.get("recordedAtUtc") or not publication.get("request"):
            raise ValueError("Explicit publication request does not identify this exact ZIP")
        return
    qa = manifest.get("qa", {})
    if qa.get("approved") is not True or qa.get("archiveSha256") != manifest["archive"]["sha256"]:
        raise ValueError("Neither explicit publication request nor QA approval identifies this exact ZIP")
    if not qa.get("evidence") or not qa.get("reviewedAtUtc"):
        raise ValueError("QA approval requires recorded evidence and review time")

def load_manifest(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if value["schema"] != 1 or value["repository"] != REPOSITORY or value["tag"] != TAG:
        raise ValueError("Unexpected release target")
    for name in (value["patch"]["file"], value["archive"]["file"]):
        if Path(name).name != name or "/" in name or "\\" in name:
            raise ValueError("Unsafe local filename")
    return value

def verify_archive(path, manifest):
    require_file(path, manifest["archive"])
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or archive.testzip() is not None:
            raise ValueError("Duplicate entries or invalid ZIP CRC")
        if any(PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts for name in names):
            raise ValueError("Unsafe ZIP path")
        provenance = json.loads(archive.read("Windows/build-provenance.json"))
        if provenance["sourceCommit"] != manifest["source"]["commit"] or provenance["sourceAssetSha256"] != manifest["source"]["assetSha256"]:
            raise ValueError("Packaged source provenance mismatch")
        normal = archive.read("Windows/Play-GeoChase.cmd")
        dx11 = archive.read("Windows/Play-GeoChase-DX11.cmd")
        if b"-d3d11" in normal or b"-d3d11" not in dx11 or any(b"userdir" in value.lower() for value in (normal, dx11)):
            raise ValueError("Launcher configuration mismatch")
    return len(names)

def reconstruct(manifest_path, work_dir, baseline=None):
    manifest_path = Path(manifest_path).resolve()
    manifest = load_manifest(manifest_path)
    patch = manifest_path.parent / manifest["patch"]["file"]
    require_file(patch, manifest["patch"])
    if baseline is not None:
        require_file(baseline, manifest["baseline"])
    work_dir = Path(work_dir).resolve()
    work_dir.mkdir(parents=True, exist_ok=False)
    target = work_dir / "GeoChase.zip"
    if baseline is None:
        request = urllib.request.Request(manifest["baseline"]["url"], headers={"User-Agent": "GeoChase-release-verifier"})
        with urllib.request.urlopen(request, timeout=120) as response, target.open("xb") as output:
            shutil.copyfileobj(response, output)
    else:
        shutil.copyfile(baseline, target)
    require_file(target, manifest["baseline"])
    for mode in (["--check"], []):
        subprocess.run(["git", "apply", *mode, "--", str(patch)], cwd=work_dir, check=True)
    entries = verify_archive(target, manifest)
    output = work_dir / manifest["archive"]["file"]
    target.rename(output)
    (work_dir / "SHA256SUMS.txt").write_text(
        manifest["archive"]["sha256"] + "  " + output.name + "\n", encoding="ascii")
    provenance = {
        "schema": 1, "source": manifest["source"], "archive": manifest["archive"],
        "qa": manifest["qa"], "publication": manifest.get("publication", {}),
        "reconstruction": {"baseline": manifest["baseline"], "patch": manifest["patch"]},
        "verifiedZipEntries": entries,
        "embeddedProvenance": "The ZIP records the packaging-time QA state. This sidecar records the later release review."
    }
    (work_dir / "release-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    return {"sha256": digest(output), "bytes": output.stat().st_size, "zipCrcVerified": True,
            "entries": entries, "qaApproved": manifest["qa"]["approved"], "published": False}

def verify_upload(manifest, release, work_dir):
    require_publication(manifest)
    if release["tag_name"] != manifest["tag"]:
        raise ValueError("Uploaded release tag differs")
    expected_names = {manifest["archive"]["file"], "SHA256SUMS.txt", "release-provenance.json"}
    assets = {item["name"]: item for item in release["assets"]}
    if set(assets) != expected_names or len(release["assets"]) != len(expected_names):
        raise ValueError("Uploaded assets differ")
    for name in expected_names:
        path = Path(work_dir) / name
        item = assets[name]
        if item["state"] != "uploaded" or item["size"] != path.stat().st_size or item.get("digest") != "sha256:" + digest(path):
            raise ValueError("Uploaded asset identity mismatch: " + name)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check-publication", action="store_true")
    modes.add_argument("--reconstruct", action="store_true")
    modes.add_argument("--verify-upload", type=Path)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    manifest = load_manifest(args.manifest)
    if args.check_publication:
        require_publication(manifest)
        print("Publication authorized for exact ZIP; visual QA approved:", manifest["qa"]["approved"])
    elif args.verify_upload:
        if args.work_dir is None:
            parser.error("--work-dir is required")
        verify_upload(manifest, json.loads(args.verify_upload.read_text(encoding="utf-8")), args.work_dir)
        print("All uploaded asset digests and sizes match")
    else:
        if args.work_dir is None:
            parser.error("--work-dir is required")
        print(json.dumps(reconstruct(args.manifest, args.work_dir, args.baseline), indent=2))

if __name__ == "__main__":
    main()
