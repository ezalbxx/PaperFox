"""Build a shareable Windows x64 release from a clean Python environment."""
import argparse
import importlib.metadata
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


def create_icon(source: Path, target: Path):
    import fitz
    from PIL import Image

    with fitz.open("svg", source.read_bytes()) as document:
        page = document[0]
        scale = 1024 / page.rect.width
        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=True)
    sizes = [(size, size) for size in (16, 20, 24, 32, 40, 48, 64, 128, 256)]
    with Image.open(io.BytesIO(pixmap.tobytes("png"))) as artwork:
        icon = artwork.resize(sizes[-1], Image.Resampling.LANCZOS)
        icon.save(target, sizes=sizes)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("staging", type=Path, help="External build directory")
    parser.add_argument("output", type=Path, help="Path to the release zip")
    parser.add_argument("--third-party", type=Path, help="Directory holding the fonts and Tectonic archive")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    stage = args.staging.resolve()
    assets = args.third_party.resolve() if args.third_party else stage / "third-party"
    fonts = ("PaperFoxSerif.otf", "PaperFoxSans.otf", "OFL.txt")
    for path in [assets / "tectonic.zip", assets / "Tectonic-LICENSE",
                 *(assets / "fonts" / f for f in fonts)]:
        if not path.is_file():
            parser.error(f"Missing release dependency: {path}")
    dist = stage / "dist"
    source_path = root / "src"
    stage.mkdir(parents=True, exist_ok=True)
    icon = stage / "PaperFox.ico"
    create_icon(source_path / "myagent/web_static/paperfox-desktop.svg", icon)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--onedir", "--windowed",
                    "--noupx", "--name", "PaperFox", "--icon", str(icon), "--paths", str(source_path),
                    "--collect-data", "myagent", "--collect-submodules", "myagent",
                    "--collect-data", "matplotlib", "--collect-data", "rapidocr_onnxruntime",
                    "--distpath", str(dist),
                    "--workpath", str(stage / "windows-build"), "--specpath", str(stage),
                    str(root / "scripts/paperfox_windows.py")], cwd=root,
                   env={**os.environ, "PYTHONPATH": str(source_path), "PYTHONUTF8": "1"}, check=True)
    package = dist / "PaperFox"
    shutil.copy2(icon, package / icon.name)
    (package / "tectonic").mkdir(exist_ok=True)
    (package / "fonts").mkdir(exist_ok=True)
    with zipfile.ZipFile(assets / "tectonic.zip") as archive:
        with archive.open("tectonic.exe") as source, (package / "tectonic/tectonic.exe").open("wb") as target:
            shutil.copyfileobj(source, target)
    shutil.copy2(assets / "Tectonic-LICENSE", package / "tectonic/LICENSE")
    for name in fonts:
        shutil.copy2(assets / "fonts" / name, package / "fonts" / name)
    shutil.copy2(root / "docs/paperfox-windows-test.md", package / "使用说明.txt")
    requirements = subprocess.check_output([sys.executable, "-m", "pip", "list", "--format=freeze"], text=True)
    (package / "runtime-requirements.txt").write_text(requirements, encoding="utf-8")
    notices = package / "third-party-licenses"
    notices.mkdir(exist_ok=True)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        shutil.copy2(python_license, notices / "CPython.txt")
    for distribution in importlib.metadata.distributions():
        license_files = [item for item in distribution.files or ()
                         if ".dist-info" in str(item) and item.name.lower().startswith(("license", "copying", "notice"))]
        if license_files:
            folder = notices / distribution.metadata["Name"]
            folder.mkdir(exist_ok=True)
            for item in license_files:
                shutil.copy2(distribution.locate_file(item), folder / item.name)
    shutil.copy2(root / "docs/paperfox-release-components.md", package / "组件与来源.md")
    # Provide the exact application source used by this build. No project data is collected.
    with zipfile.ZipFile(package / "PaperFox-source.zip", "w", zipfile.ZIP_DEFLATED) as source_zip:
        files = [p for p in (root / "src/myagent").rglob("*")
                 if p.is_file() and "__pycache__" not in p.parts and p.suffix in
                 {".py", ".md", ".json", ".html", ".css", ".js", ".svg", ".png", ".txt", ".ps1", ".mjs"}]
        files += [root / name for name in ("pyproject.toml", "scripts/paperfox_windows.py",
                                          "scripts/build_paperfox_windows.py", "docs/paperfox-windows-test.md",
                                          "docs/paperfox-release-components.md")]
        for path in sorted(files):
            source_zip.write(path, path.relative_to(root).as_posix())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED, compresslevel=4) as delivery:
        for path in sorted(package.rglob("*")):
            if path.is_file():
                delivery.write(path, path.relative_to(dist).as_posix())
    print(args.output.resolve())


if __name__ == "__main__":
    main()
