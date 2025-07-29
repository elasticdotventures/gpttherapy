#!/usr/bin/env python3
"""
Project compression script for GPT Therapy.

Creates compressed archives of the project for backup, distribution, or sharing.
Excludes development artifacts and large files.

Usage:
    python scripts/compress_project.py [--format tar.gz|zip] [--output-dir dist/]
"""

import argparse
import os
import tarfile
import zipfile
from datetime import datetime
from pathlib import Path


def should_exclude(path: Path, project_root: Path) -> bool:
    """Determine if a file/directory should be excluded from the archive."""
    relative_path = path.relative_to(project_root)
    path_parts = relative_path.parts

    # Exclude patterns
    exclude_patterns = {
        # Development artifacts
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "node_modules",
        ".coverage",
        # IDE and editor files
        ".vscode",
        ".idea",
        "*.swp",
        "*.swo",
        "*~",
        # OS files
        ".DS_Store",
        "Thumbs.db",
        "*.tmp",
        # Build artifacts
        "dist",
        "build",
        "*.egg-info",
        # Large database files
        "context.db",
        "*.db-journal",
        # Log files
        "logs",
        "*.log",
        # Git (optional - comment out if you want git history)
        ".git",
    }

    # Check if any part of the path matches exclusion patterns
    for part in path_parts:
        if part in exclude_patterns:
            return True

        # Check wildcard patterns
        for pattern in exclude_patterns:
            if pattern.startswith("*") and part.endswith(pattern[1:]):
                return True

    # Exclude files larger than 10MB
    if path.is_file() and path.stat().st_size > 10 * 1024 * 1024:
        return True

    return False


def create_tar_archive(source_dir: Path, output_file: Path) -> None:
    """Create a tar.gz archive."""
    print(f"Creating tar.gz archive: {output_file}")

    with tarfile.open(output_file, "w:gz") as tar:
        for root, dirs, files in os.walk(source_dir):
            # Filter directories in-place to skip excluded ones
            dirs[:] = [
                d for d in dirs if not should_exclude(Path(root) / d, source_dir)
            ]

            for file in files:
                file_path = Path(root) / file
                if not should_exclude(file_path, source_dir):
                    arcname = file_path.relative_to(source_dir)
                    tar.add(file_path, arcname=arcname)


def create_zip_archive(source_dir: Path, output_file: Path) -> None:
    """Create a ZIP archive."""
    print(f"Creating ZIP archive: {output_file}")

    with zipfile.ZipFile(output_file, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(source_dir):
            # Filter directories in-place to skip excluded ones
            dirs[:] = [
                d for d in dirs if not should_exclude(Path(root) / d, source_dir)
            ]

            for file in files:
                file_path = Path(root) / file
                if not should_exclude(file_path, source_dir):
                    arcname = file_path.relative_to(source_dir)
                    zf.write(file_path, arcname)


def get_file_size(file_path: Path) -> str:
    """Get human-readable file size."""
    size = file_path.stat().st_size
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def main():
    parser = argparse.ArgumentParser(description="Compress GPT Therapy project")
    parser.add_argument(
        "--format",
        choices=["tar.gz", "zip"],
        default="tar.gz",
        help="Archive format (default: tar.gz)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("dist"),
        help="Output directory (default: dist/)",
    )
    parser.add_argument(
        "--include-git", action="store_true", help="Include .git directory in archive"
    )

    args = parser.parse_args()

    # Determine project root and current timestamp
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Create output directory
    output_dir = project_root / args.output_dir
    output_dir.mkdir(exist_ok=True)

    # Generate filename
    if args.format == "tar.gz":
        filename = f"gpttherapy_{timestamp}.tar.gz"
    else:
        filename = f"gpttherapy_{timestamp}.zip"

    output_file = output_dir / filename

    print("Compressing project...")
    print(f"Source: {project_root}")
    print(f"Output: {output_file}")
    print(f"Format: {args.format}")

    try:
        # Temporarily modify exclusion logic if git should be included
        if args.include_git:
            # Remove .git from exclusion patterns temporarily
            # This is handled in the should_exclude function
            pass

        # Create archive based on format
        if args.format == "tar.gz":
            create_tar_archive(project_root, output_file)
        else:
            create_zip_archive(project_root, output_file)

        # Show results
        archive_size = get_file_size(output_file)
        print(f"✅ Archive created: {output_file}")
        print(f"📦 Archive size: {archive_size}")

        # Count files in archive
        if args.format == "tar.gz":
            with tarfile.open(output_file, "r:gz") as tar:
                file_count = len(tar.getnames())
        else:
            with zipfile.ZipFile(output_file, "r") as zf:
                file_count = len(zf.namelist())

        print(f"📁 Files in archive: {file_count}")

    except Exception as e:
        print(f"❌ Compression failed: {e}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
