"""Create a GitHub upload ZIP from explicit public file types and directories."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
PROJECT_TITLE = "Treasury Futures Execution Analytics & TCA Engine"
PUBLIC_TYPES = {
    "treasury_futures_execution_analytics_tca_engine": {".py"},
    "scripts": {".py", ".q"},
    "tests": {".py"},
    "dashboard": {".html"},
    "q": {".q"},
    "docs": {".md", ".json", ".png"},
}


def public_files() -> list[Path]:
    files = [ROOT / name for name in (".gitignore", "README.md", "pyproject.toml")]
    for directory, suffixes in PUBLIC_TYPES.items():
        for path in (ROOT / directory).rglob("*"):
            relative = path.relative_to(ROOT)
            if any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
                raise ValueError(f"Public path must stay within the project: {relative}")
            if path.is_file() and path.suffix in suffixes:
                files.append(path)
    return sorted(files)


def main() -> None:
    files = public_files()
    output = ROOT / "dist" / f"{PROJECT_TITLE}.zip"
    output.parent.mkdir(exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, f"{PROJECT_TITLE}/{path.relative_to(ROOT).as_posix()}")
    manifest = output.with_suffix(".manifest.txt")
    manifest.write_text(
        "\n".join(f"{PROJECT_TITLE}/{p.relative_to(ROOT).as_posix()}" for p in files) + "\n",
        encoding="utf-8",
    )
    print(f"Created {output.name}: {len(files)} files, {output.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()

