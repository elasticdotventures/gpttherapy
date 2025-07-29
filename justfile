# GPT Therapy Project Commands
# Run with: just <command>

tf:="tofu"

# Default recipe - show available commands
default:
    @just --list

# Setup development environment
setup:
    uv sync --dev
    pre-commit install
    @echo "✅ Development environment setup complete"

# Run all tests
test:
    uv run pytest tests/ -v --cov=src/

# Run linting and formatting
lint:
    uv run ruff check .
    uv run black --check .
    uv run mypy src/

# Fix linting issues
fix:
    uv run ruff check --fix .
    uv run black .

# Run pre-commit hooks on all files
pre-commit:
    pre-commit run --all-files

# Deploy infrastructure with Terraform
tf-deploy:
    cd terraform && {{tf}} init && {{tf}} plan && {{tf}} apply

# Show Terraform outputs
tf-outputs:
    cd terraform && {{tf}} output

# Extract AWS credentials from Terraform state and set GitHub secrets
setup-github-secrets:
    #!/usr/bin/env bash
    set -euo pipefail

    echo "🔑 Extracting AWS credentials from Terraform state..."

    # Change to terraform directory
    cd terraform

    # Extract credentials from Terraform outputs
    ACCESS_KEY_ID=$({{tf}} output -raw github_actions_access_key_id)
    SECRET_ACCESS_KEY=$({{tf}} output -raw github_actions_secret_access_key)

    if [[ -z "$ACCESS_KEY_ID" || -z "$SECRET_ACCESS_KEY" ]]; then
        echo "❌ Failed to extract credentials from Terraform state"
        echo "Make sure you've run 'just tf-deploy' first"
        exit 1
    fi

    echo "✅ Credentials extracted successfully"
    echo "🚀 Setting GitHub repository secrets..."

    # Set GitHub secrets using gh CLI
    echo "$ACCESS_KEY_ID" | gh secret set AWS_ACCESS_KEY_ID
    echo "$SECRET_ACCESS_KEY" | gh secret set AWS_SECRET_ACCESS_KEY

# Complete setup: deploy infrastructure and configure GitHub secrets
complete-setup: tf-deploy setup-github-secrets
    @echo "🎉 Complete setup finished!"
    @echo ""
    @echo "Next steps:"
    @echo "1. Push your code to trigger CI/CD pipeline"
    @echo "2. Check GitHub Actions for deployment status"

# Clean up Terraform resources (use with caution!)
tf-destroy:
    #!/usr/bin/env bash
    echo "⚠️  This will destroy all Terraform resources!"
    echo "Press Ctrl+C to cancel, or Enter to continue..."
    read
    cd terraform && {{tf}} destroy

# Show project status
status:
    @echo "📊 Project Status"
    @echo "=================="
    @echo ""
    @echo "🐍 Python version:"
    @python3 --version
    @echo ""
    @echo "📦 UV status:"
    @uv --version
    @echo ""
    @echo "🏗️  Terraform status:"
    @cd terraform && {{tf}} version
    @echo ""
    @echo "🐙 GitHub CLI status:"
    @gh --version
    @echo ""
    @echo "📋 GitHub secrets:"
    @gh secret list || echo "❌ Not in a GitHub repository or gh not authenticated"

# Run development server (placeholder for future use)
dev:
    @echo "🚧 Development server not implemented yet"
    @echo "This project deploys to AWS Lambda via GitHub Actions"

# View logs from AWS Lambda
logs:
    @echo "📋 Recent Lambda logs (last 10 minutes):"
    aws logs tail /aws/lambda/gpttherapy-handler --since 10m --follow

# Build Lambda deployment package
build-lambda:
    @echo "🏗️  Building Lambda deployment package..."
    mkdir -p dist
    uv run python scripts/build_lambda.py
    @echo "✅ Lambda package built successfully"

deploy-lambdas:
    @echo "🚀 Deploying Lambda functions..."
    aws lambda update-function-code --function-name gpttherapy-handler --zip-file fileb://dist/lambda-deployment.zip
    aws lambda update-function-code --function-name gpttherapy-timeout-processor --zip-file fileb://dist/timeout-deployment.zip
    @echo "✅ Lambda functions deployed successfully"

# Compress project for distribution/backup
compress FORMAT="tar.gz":
    @echo "🗜️  Compressing project ({{FORMAT}})..."
    mkdir -p dist
    uv run python scripts/compress_project.py --format {{FORMAT}}
    @echo "✅ Project compressed successfully"

# Compress project with git history
compress-with-git FORMAT="tar.gz":
    @echo "🗜️  Compressing project with git ({{FORMAT}})..."
    mkdir -p dist
    uv run python scripts/compress_project.py --format {{FORMAT}} --include-git
    @echo "✅ Project compressed with git history"

# Clean build artifacts and compressed files
clean:
    @echo "🧹 Cleaning build artifacts..."
    rm -rf dist/
    rm -rf build/
    rm -rf *.egg-info/
    find . -type d -name "__pycache__" -exec rm -rf {} +
    find . -type f -name "*.pyc" -delete
    find . -type f -name "*.pyo" -delete
    @echo "✅ Cleanup complete"