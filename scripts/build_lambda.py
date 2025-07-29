#!/usr/bin/env python3
"""
Lambda function build and compression script for GPT Therapy.

This script creates a deployment-ready ZIP file containing:
- Source code from src/
- Runtime dependencies (excluding dev dependencies)
- Game configuration files

Usage:
    python scripts/build_lambda.py [--output-dir dist/]
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def run_command(cmd: list[str], cwd: Path = None) -> subprocess.CompletedProcess:
    """Run a command and return the result."""
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error running command: {' '.join(cmd)}")
        print(f"stdout: {result.stdout}")
        print(f"stderr: {result.stderr}")
        sys.exit(1)
    return result


def install_dependencies(temp_dir: Path, project_root: Path) -> None:
    """Install production dependencies to temporary directory."""
    print("Installing production dependencies...")

    # First, export requirements to a file (production only)
    requirements_file = temp_dir / "requirements.txt"
    run_command(
        [
            "uv",
            "export",
            "--no-dev",
            "--format",
            "requirements-txt",
            "--output-file",
            str(requirements_file),
        ],
        cwd=project_root,
    )

    # Install from requirements file
    run_command(
        [
            "uv",
            "pip",
            "install",
            "--target",
            str(temp_dir / "packages"),
            "--python-version",
            "3.12",
            "--requirement",
            str(requirements_file),
        ],
        cwd=project_root,
    )


def copy_source_code(temp_dir: Path, project_root: Path) -> None:
    """Copy source code to temporary directory and fix imports."""
    print("Copying source code...")

    src_dir = project_root / "src"
    dest_dir = temp_dir / "src"

    if src_dir.exists():
        shutil.copytree(src_dir, dest_dir)

        # Fix relative imports for Lambda deployment
        print("Converting relative imports to absolute imports for Lambda...")
        for py_file in dest_dir.glob("*.py"):
            fix_imports_for_lambda(py_file)
    else:
        raise FileNotFoundError(f"Source directory not found: {src_dir}")


def fix_imports_for_lambda(py_file: Path) -> None:
    """Convert relative imports to absolute imports for Lambda deployment."""
    content = py_file.read_text()

    # Convert relative imports like "from .module import" to "from module import"
    import re

    content = re.sub(
        r"^from \.([a-zA-Z_][a-zA-Z0-9_]*) import",
        r"from \1 import",
        content,
        flags=re.MULTILINE,
    )

    py_file.write_text(content)


def copy_game_configs(temp_dir: Path, project_root: Path) -> None:
    """Copy game configuration files."""
    print("Copying game configurations...")

    games_dir = project_root / "games"
    if games_dir.exists():
        dest_dir = temp_dir / "games"
        shutil.copytree(games_dir, dest_dir)


def create_lambda_zip(temp_dir: Path, output_file: Path) -> None:
    """Create ZIP file for Lambda deployment."""
    print(f"Creating deployment package: {output_file}")

    with zipfile.ZipFile(output_file, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add dependencies from packages/ to root
        packages_dir = temp_dir / "packages"
        if packages_dir.exists():
            for root, dirs, files in os.walk(packages_dir):
                # Skip __pycache__ and .pyc files
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for file in files:
                    if not file.endswith(".pyc"):
                        file_path = Path(root) / file
                        arcname = file_path.relative_to(packages_dir)
                        zf.write(file_path, arcname)

        # Add source code
        src_dir = temp_dir / "src"
        if src_dir.exists():
            for root, dirs, files in os.walk(src_dir):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for file in files:
                    if not file.endswith(".pyc"):
                        file_path = Path(root) / file
                        arcname = file_path.relative_to(src_dir)
                        zf.write(file_path, arcname)

        # Add game configurations
        games_dir = temp_dir / "games"
        if games_dir.exists():
            for root, _, files in os.walk(games_dir):
                for file in files:
                    file_path = Path(root) / file
                    arcname = file_path.relative_to(temp_dir)
                    zf.write(file_path, arcname)


def get_package_size(file_path: Path) -> str:
    """Get human-readable file size."""
    size = file_path.stat().st_size
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def main():
    parser = argparse.ArgumentParser(description="Build Lambda deployment package")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("dist"),
        help="Output directory for deployment package (default: dist/)",
    )
    parser.add_argument(
        "--filename",
        type=str,
        default="gpttherapy-lambda.zip",
        help="Output filename (default: gpttherapy-lambda.zip)",
    )

    args = parser.parse_args()

    # Determine project root
    script_dir = Path(__file__).parent
    project_root = script_dir.parent

    # Create output directory
    output_dir = project_root / args.output_dir
    output_dir.mkdir(exist_ok=True)
    output_file = output_dir / args.filename

    print("Building Lambda deployment package...")
    print(f"Project root: {project_root}")
    print(f"Output file: {output_file}")

    # Create temporary directory for building
    with tempfile.TemporaryDirectory() as temp_dir_str:
        temp_dir = Path(temp_dir_str)

        try:
            # Install dependencies
            install_dependencies(temp_dir, project_root)

            # Copy source code
            copy_source_code(temp_dir, project_root)

            # Copy game configurations
            copy_game_configs(temp_dir, project_root)

            # Create ZIP file
            create_lambda_zip(temp_dir, output_file)

            # Show results
            package_size = get_package_size(output_file)
            print(f"✅ Deployment package created: {output_file}")
            print(f"📦 Package size: {package_size}")

            # Validate ZIP file
            with zipfile.ZipFile(output_file, "r") as zf:
                file_count = len(zf.namelist())
                print(f"📁 Files in package: {file_count}")

                # Check for lambda handler
                if "lambda_function.py" in zf.namelist():
                    print("✅ Lambda handler found")
                else:
                    print("⚠️  Lambda handler (lambda_function.py) not found")

        except Exception as e:
            print(f"❌ Build failed: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
