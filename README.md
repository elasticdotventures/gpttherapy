# gpttherapy


    ☐ Create game/therapy agent configurations
     ☐ Implement session state management (S3/DynamoDB)
     ☐ Add Bedrock/LLM integration for AI responses
     ☐ Create email templates (init, invite, response)
     ☐ Implement turn-based game logic
     ☐ Add session timeout and reminder system
     ☐ Create game state persistence layer
     ☐ Add comprehensive error handling and logging
     ☐ Implement email parsing and validation
     ☐ Add monitoring and observability


---

📄 Product Requirements Document: PromptExecution Mail-based Turn Engine
✅ Objective
Design and implement a serverless, email-only, asynchronous communication system mediated by AI agents (narrators). It enables interactive storytelling or guided therapeutic dialogue via email, turn by turn. Primary use cases:

- 🧙‍♂️ Narrative Role-Playing Game (e.g., dungeon.post)
- 🫂 Couples or group therapy (e.g., intimacy.post)

## 🔑 Key Features
Turn-based system: Game or session advances only after all required participants have responded.

Email interface only: No frontend; interactions are via standard email clients.

Multiple concurrent games: Yes.

Session memory & logic: Game state tracked with turn counters, timeouts, and player inputs.

LLM-narrated turns: GPT-style narrator processes input, generates cohesive narrative or prompts, and sends back to players.

Session expiration: After two missed turns by any player or explicit quit signals.

## 🧠 Agent Architecture
Narrator/Agent: Each game type has a dedicated narrator prompt file (e.g., AGENT.md) that governs tone, logic, memory handling, and response style.

Pluggable missions or personas: Text-based prompts stored in repo as .md files, defining the goals or therapeutic framing.

## 📁 Filesystem Layout
```
games/
  dungeon/
    AGENT.md
    init-template.md
    invite-template.md
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
```
AGENT.md: defines LLM’s role and tone

init-template.md: email template sent to a new participant

invite-template.md: forwarded to invite others

Each game/therapy mode supports multiple scenarios (missions)

## 💡 User Flow
Start: User emails dungeon@dungeon.post

Form Response: Receives init-template.md (form-style template), fills it in, and replies

Invite Others: Receives invite-template.md with embedded session ID, forwards to friends

Game Starts: After minimum player count is met, game begins

Turns: Each player replies to turns by email. Game proceeds when all reply or on timeout

LLM Output: Narrator replies with updated scenario and prompt for next move

## 🗃️ Storage Design
Backend: AWS (S3 + DynamoDB)

S3 Bucket: Stores per-game directories

README.md: Game rules

turns/: Sequential turn files (one per turn, per player, and LLM response)

emails/: Raw incoming/outgoing email text

DynamoDB Tables:

Games: game_id, agent, mission, max_turns, timeout_minutes

Sessions: session_id, game_id, player_emails, current_turn, last_response_at

Turns: session_id, turn_number, player_email, content, timestamp

Reminders: track pending turn responses for scheduling retries

## ⏱️ Timing / DAG Execution
Serverless event-driven logic using:

AWS Lambda: to process email events (via SES)

Amazon EventBridge (or Step Functions): to schedule follow-up actions (e.g. reminder, timeout handling)

DAG-like behavior handled via:

Serialization of each step's outcome (turn inputs)

Triggering "next node" (next action) based on completion or timeout

📧 Email System
Inbound: AWS SES → Lambda → Email Parser → Dispatcher

Outbound: SES → signed reply with LLM-generated content

Session Routing: email address encodes session ID (123@dungeon.post)

Reminder System: Sends follow-ups for pending responses

🧪 MVP Completion Criteria
 Create 1 game and 1 therapy experience (with AGENT.md, init-template.md, and invite-template.md)

 Ingest and route inbound emails via SES and Lambda

 Store turn logs and LLM responses in S3 and DynamoDB

 Wait for all players' turn responses before advancing

 Handle turn timeouts and reminders

 Trigger final wrap-up message when game ends (by victory, timeout, or exit)

🛠️ Open Questions
What are the constraints on email formatting to ensure compatibility across clients?

Should players ever see anonymized or summarized inputs from others?

Should there be any verification to prevent spoofed email?

Should the LLM persist memory or regenerate from context every time?

How will DAG structure be defined and versioned per game?

If this looks good, I can now generate:

📘 A full PRD (in markdown)

🧪 MVP Checklist

🔧 Terraform/AWS architecture plan

🧬 Game format specification (schemas, examples)

Would you like me to proceed with those?

---

You want to build rapid MVPs, with minimal boilerplate.

You’re comfortable managing workflows with tools like Apache Airflow, Prefect, or Dagster (which all favor Python).

You expect to do NLP-style preprocessing or postprocessing.

You want to use AWS Lambda with fewer cold start concerns for simple I/O-bound tasks.

I think dagster is a good fit for our MVP

----
Option B: AWS SES + Lambda (Full AWS-native)
SES receives inbound email (must verify domain)

Triggers Lambda directly or via S3 → Lambda pipeline

Process as above

⚠️ SES inbound is a bit fiddlier than Mailgun but no third-party required.


