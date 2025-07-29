# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

GPTTherapy is a serverless, email-only, asynchronous communication system mediated by AI agents (narrators). It enables interactive storytelling or guided therapeutic dialogue via email, turn by turn. The system supports:

- 🧙‍♂️ Narrative Role-Playing Games (e.g., dungeon.post)
- 🫂 Couples or group therapy (e.g., intimacy.post)

## Architecture

### Core Components
- **Turn-based system**: Game/session advances only after all required participants respond
- **Email interface only**: No frontend; all interactions via standard email clients
- **Session memory & logic**: Game state tracked with turn counters, timeouts, and player inputs
- **LLM-narrated turns**: AI narrator processes input, generates cohesive narrative/prompts

### Storage Design
- **Backend**: AWS (S3 + DynamoDB) or NeonDB (PostgreSQL) for production
- **Context Portal**: Database-agnostic system for tracking context, decisions, and progress

### Database Schema (context_portal/)
- `active_context`: Current session context
- `active_context_history`: Version history of context changes
- `context_links`: Relationships between workspace items
- `custom_data`: Key-value storage with categories
- `decisions`: Decision tracking with rationale and implementation details
- `product_context`: Product-level context information
- `progress_entries`: Hierarchical progress tracking
- `system_patterns`: Reusable system patterns

## Development Environment

### Technology Stack
- **Python 3.12+**: Primary language with `uv` for packaging
- **NeonDB (PostgreSQL)** or **DynamoDB**: Production database
- **Alembic**: Database migrations
- **OpenTofu (alias: tf)**: Infrastructure as Code (preferred over Terraform)
- **AWS Services**: SES (email), Lambda (serverless), S3 (storage)
- **Dagster**: Workflow orchestration (recommended for MVP)

### Development Commands (via justfile)
```bash
# Setup and deployment
just setup                 # Setup development environment
just complete-setup        # Deploy infrastructure + configure GitHub secrets
just tf-deploy             # Deploy infrastructure only
just setup-github-secrets  # Configure GitHub secrets from Terraform state

# Development workflow
just test                  # Run all tests
just lint                  # Check code quality
just fix                   # Fix linting issues
just pre-commit            # Run pre-commit hooks

# Monitoring and status
just status                # Show project and tool status
just check-github-secrets  # Verify GitHub secrets are set
just logs                  # View Lambda function logs
just tf-outputs            # Show Terraform outputs

# Manual commands (if needed)
uv sync --dev             # Install dev dependencies
uv add package-name       # Add new dependency
cd terraform && tf init && tf plan && tf apply  # Manual Terraform

# Database migrations
cd context_portal && alembic upgrade head
cd context_portal && alembic revision --autogenerate -m "Description"
```

### Project Structure
```
src/
  __init__.py
  lambda_function.py      # Main Lambda handler

tests/
  __init__.py
  test_lambda_function.py # Lambda handler tests

terraform/
  backend.tf              # AWS provider and backend config
  gpttherapy-lambda.tf    # Lambda function infrastructure
  github-secrets.tf       # IAM user and access keys for GitHub Actions

.github/
  workflows/
    deploy.yml            # CI/CD pipeline for Lambda deployment

games/                    # Game/therapy configurations (to be created)
  dungeon/
    AGENT.md              # LLM role and tone definition
    init-template.md      # New participant email template
    invite-template.md    # Invitation template
    missions/
      heist.md
      rescue.md
  intimacy/
    AGENT.md
    init-template.md
    invite-template.md
    missions/
      conflict-resolution.md
      gratitude.md

context_portal/           # Database and context management
  alembic/
  alembic.ini
  context.db

justfile                 # Task runner with common commands
pyproject.toml           # Python project configuration
.python-version          # Python version (3.12)
.pre-commit-config.yaml  # Code quality hooks
```

## Key Development Patterns

### Agent Configuration
Each game type has:
- `AGENT.md`: Defines LLM's role, tone, and behavior
- `init-template.md`: Template for onboarding new participants
- `invite-template.md`: Template for inviting others to join
- `missions/`: Scenario-specific prompts and configurations

### Email Flow
1. User emails `game@domain.post` (e.g., `dungeon@dungeon.post`)
2. System sends `init-template.md` as form-style response
3. User fills and replies to form
4. System sends `invite-template.md` with session ID for multiplayer
5. Game begins when minimum player count met
6. Turn-based email exchange with AI narrator

### Context Management
The context portal system tracks:
- **Active context**: Current working context
- **Decisions**: Design decisions with rationale
- **Progress**: Hierarchical task tracking
- **Links**: Relationships between different items
- **Patterns**: Reusable system patterns

## b00t Integration

This project uses the b00t framework for development workflow:

```bash
# Check agent identity and context
b00t whoami

# Available b00t commands
b00t --help

# Create checkpoint (commit + test)
b00t checkpoint
```

## Testing Strategy

- Use test data in JSON format, never embedded in test code
- Follow TDD: write tests first, then implement
- Verify all changes pass tests before committing
- Use `chronic` command to reduce noise in test output

## AWS/Serverless Architecture

### Production Components
- **AWS SES**: Inbound/outbound email processing
- **AWS Lambda**: Serverless event processing
- **Amazon EventBridge**: Scheduling and workflow coordination
- **S3**: Game data and turn history storage
- **DynamoDB**: Session state and metadata

### Local Development
- NeonDB or local PostgreSQL for database testing
- File system replaces S3 for local storage
- Use Dagster for workflow orchestration and testing
- OpenTofu for infrastructure provisioning and management

## Email Architecture Options

### Option A: Dagster + AWS Lambda (Recommended for MVP)
- Dagster handles workflow orchestration
- AWS Lambda processes email events
- Good for NLP preprocessing/postprocessing
- Fewer cold start concerns for I/O-bound tasks

### Option B: AWS SES + Lambda (Full AWS-native)
- SES receives inbound email (requires domain verification)
- Triggers Lambda directly or via S3 → Lambda pipeline
- ⚠️ SES inbound more complex than third-party options

## Development Workflow

### Initial Setup
```bash
# One-command setup (recommended)
just complete-setup

# Or step by step:
just setup                 # Install dependencies and pre-commit hooks
just tf-deploy             # Deploy AWS infrastructure
just setup-github-secrets  # Configure GitHub Actions secrets
```

### CI/CD Pipeline
- **GitHub Actions** handles automated testing and deployment
- **Tests run** on every push: linting, type checking, unit tests
- **Auto-deployment** to Lambda function on main branch push
- **AWS credentials** automatically provisioned via Terraform:
  - IAM user `gpttherapy-github-actions` with minimal permissions
  - Access keys stored as GitHub secrets via `just setup-github-secrets`
  - Scoped to only Lambda deployment permissions

### Lambda Function Structure
- **Handler**: `src/lambda_function.py:lambda_handler`
- **Runtime**: Python 3.12
- **Triggers**: SES email events
- **Permissions**: S3, SES, Bedrock access via IAM role

## Important Notes

- **Infrastructure**: Managed by OpenTofu in `terraform/` directory
- **Task Runner**: Use `just` commands for all common operations
- **Security**: GitHub Actions credentials automatically provisioned with minimal IAM permissions
- **Deployment**: Fully automated via GitHub Actions on main branch push
- **Email routing**: Uses session ID encoding in addresses (e.g., `123@dungeon.promptexecution.com`)
- **State management**: All game state persists between turns for narrative continuity
- **Package management**: Use `uv` for all Python dependencies
- **Quality gates**: Tests, linting, and type checking must pass before deployment

### Security Best Practices
- IAM user has minimal permissions (Lambda deployment only)
- Access keys are generated and managed by Terraform
- Secrets are stored securely in GitHub repository settings
- No long-lived credentials in code or configuration files
