"""Assemble a macOS arm64 ZIP from the two compiled engines and their runtime files."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def assemble(folder, args):
    copy(args.inkling, folder / "bin/strata-inkling")
    copy(args.qwen, folder / "bin/strata")
    for name in ("atomic-turbine", "fork_demo.py", "README.md", "RELEASE_NOTES.md", "THIRD_PARTY.md"):
        copy(REPO / "atomic" / name, folder / name)
    copy(REPO / "LICENSE", folder / "LICENSE")

    vendor = REPO / "engine/third_party"
    licenses = {
        "zstd-BSD": vendor / "zstd-dec/LICENSE",
        "ggml-MIT": vendor / "strata-ggml/LICENSE",
        "ggml-headers-MIT": vendor / "ggml/LICENSE",
        "stb": vendor / "stb/LICENSE",
        "metal-cpp-Apache-2.0": args.metal_cpp / "LICENSE.txt",
    }
    for name, source in licenses.items():
        copy(source, folder / "licenses" / f"{name}.txt")

    metal = folder / "bin/metal"
    shutil.copytree(REPO / "engine/metal/kernels", metal / "kernels")
    shutil.copytree(REPO / "engine/metal/src/engine/msl", metal / "engine-msl")
    copy(REPO / "engine/include/strata/quant/strata-quant-common.h", metal / "strata-quant-common.h")
    for name in ("draft_vocab.bin", "expert-profile.bin"):
        copy(REPO / "terminal/data" / name, metal / "data" / name)

    exclude = shutil.ignore_patterns("__pycache__", "*.pyc", "test_*.py", "tests", "fixtures", "experimental-speed-projection")
    for name in ("serve", "tools", "strata_control", "strata_cli", "data"):
        shutil.copytree(REPO / "terminal" / name, folder / "terminal" / name, ignore=exclude)
    for name in ("requirements.txt", "strata.py"):
        copy(REPO / "terminal" / name, folder / "terminal" / name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inkling", type=Path)
    parser.add_argument("qwen", type=Path)
    parser.add_argument("metal_cpp", type=Path)
    parser.add_argument("--output", type=Path, default=Path("dist"))
    args = parser.parse_args()

    commit = subprocess.check_output(["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True).strip()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.output) as temp:
        staging = Path(temp)
        folder = staging / f"Atomic-Turbine-0.1.0-{commit[:8]}"
        assemble(folder, args)
        hashes = {
            str(path.relative_to(folder)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(folder.rglob("*")) if path.is_file()
        }
        manifest = dict(version="0.1.0", platform="macOS arm64", fork_commit=commit,
                        upstream="b28ca95e3e6847f2d5e317994f253b66716deeaa", files=hashes)
        (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        archive = staging / (folder.name + ".zip")
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=4) as handle:
            for path in sorted(folder.rglob("*")):
                if path.is_file():
                    handle.write(path, arcname=path.relative_to(staging))
        with zipfile.ZipFile(archive) as handle:
            bad_member = handle.testzip()
            if bad_member:
                raise ValueError(f"ZIP checksum failed for {bad_member}")
        destination = args.output / archive.name
        os.replace(archive, destination)
        checksum = hashlib.sha256(destination.read_bytes()).hexdigest()
        sidecar = staging / (archive.name + ".sha256")
        sidecar.write_text(f"{checksum}  {archive.name}\n")
        os.replace(sidecar, destination.with_suffix(".zip.sha256"))
    print(destination.resolve())


if __name__ == "__main__":
    main()
