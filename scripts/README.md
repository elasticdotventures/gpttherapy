# Compression Scripts

This directory contains scripts for compressing and packaging the GPT Therapy project.

## Scripts

### build_lambda.py
Creates a deployment-ready ZIP file for AWS Lambda containing:
- Source code from `src/`
- Production dependencies (no dev dependencies)
- Game configuration files from `games/`

**Usage:**
```bash
# Using justfile (recommended)
just build-lambda

# Direct usage
python scripts/build_lambda.py [--output-dir dist/] [--filename gpttherapy-lambda.zip]
```

**Output:** Lambda deployment package (~18MB with all dependencies)

### compress_project.py
Creates compressed archives of the entire project for backup, distribution, or sharing.

**Features:**
- Excludes development artifacts (.venv, __pycache__, etc.)
- Excludes large files (>10MB)
- Supports both tar.gz and ZIP formats
- Optional git history inclusion

**Usage:**
```bash
# Using justfile (recommended)
just compress                    # Creates tar.gz
just compress zip               # Creates ZIP file
just compress-with-git          # Includes .git directory

# Direct usage
python scripts/compress_project.py [--format tar.gz|zip] [--include-git]
```

**Output:** Project archive (~150KB without dependencies, ~60KB with git history)

## Justfile Commands

The following commands are available via the `justfile`:

- `just build-lambda` - Build Lambda deployment package
- `just compress [FORMAT]` - Compress project (default: tar.gz)
- `just compress-with-git [FORMAT]` - Compress with git history
- `just clean` - Clean build artifacts and compressed files

## File Exclusions

The compression scripts automatically exclude:

### Development Artifacts
- `.venv/` - Python virtual environment
- `__pycache__/` - Python bytecode cache
- `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/` - Tool caches
- `node_modules/` - Node.js dependencies
- `.coverage` - Coverage reports

### IDE and Editor Files
- `.vscode/`, `.idea/` - IDE configurations
- `*.swp`, `*.swo`, `*~` - Editor temporary files

### OS Files
- `.DS_Store` - macOS metadata
- `Thumbs.db` - Windows thumbnails
- `*.tmp` - Temporary files

### Build Artifacts
- `dist/`, `build/` - Build output directories
- `*.egg-info/` - Python package metadata

### Large Files
- `context.db` - SQLite database files
- `logs/` - Log directories
- Files larger than 10MB

### Version Control (optional)
- `.git/` - Git repository (excluded by default, use `--include-git` to include)

## Output Structure

All compressed files are created in the `dist/` directory:

```
dist/
├── gpttherapy-lambda.zip           # Lambda deployment package
├── gpttherapy_YYYYMMDD_HHMMSS.tar.gz  # Project archive (tar.gz)
└── gpttherapy_YYYYMMDD_HHMMSS.zip     # Project archive (zip)
```

## Lambda Package Contents

The Lambda deployment package includes:

```
gpttherapy-lambda.zip
├── boto3/                          # AWS SDK
├── pydantic/                       # Data validation
├── [other dependencies...]         # All production dependencies
├── lambda_function.py              # Main Lambda handler
├── ai_agent.py                     # AI agent implementation
├── game_engine.py                  # Game logic
├── [other source files...]        # All source code
└── games/                          # Game configurations
    ├── dungeon/
    └── intimacy/
```

## Project Archive Contents

The project archives include:

```
gpttherapy_YYYYMMDD_HHMMSS.tar.gz
├── src/                            # Source code
├── tests/                          # Test files
├── games/                          # Game configurations
├── terraform/                      # Infrastructure code
├── scripts/                        # Build scripts
├── pyproject.toml                  # Project configuration
├── justfile                        # Task runner
├── README.md                       # Project documentation
└── [other project files...]
```

## Notes

- Lambda packages include all production dependencies and are ready for deployment
- Project archives exclude dependencies and development artifacts for smaller file sizes
- All scripts use timestamp-based naming to avoid conflicts
- The `clean` command removes all build artifacts and compressed files
