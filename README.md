# Senti (Sentinel-Agent)

A modular, security-first AI agent system. Senti connects a Telegram interface to a local LLM (via Ollama), with tool execution sandboxed in Docker containers and human-in-the-loop approval for high-stakes actions.

## Architecture

```
User → Telegram → AllowedUserFilter → Orchestrator
                                         ├── LLM (Ollama via LiteLLM)
                                         ├── Memory (SQLite)
                                         ├── In-process skills (facts, datetime)
                                         └── Sandboxed skills (search, gdrive, email)
                                              └── Docker containers (read-only, no caps, nobody user)
```

**Gateway → Controller → Sandbox** — the AI never has direct, unmediated access to the host.

### Message Flow

1. User sends a Telegram message
2. `AllowedUserFilter` checks the user ID whitelist
3. Orchestrator redacts inbound text, loads conversation history
4. LLM generates a response (optionally with tool calls)
5. Tool-call loop:
   - Check if the tool requires approval → HITL inline keyboard
   - Route: sandboxed → Docker container | in-process → direct call
   - Sanitize + redact tool result
   - Re-call LLM with results
6. Redact outbound response, save to conversation memory
7. Send response back to Telegram

## Features

- **Access control** — Telegram user ID whitelist
- **Conversation memory** — sliding window buffer (configurable, default 20 messages) persisted to SQLite
- **Fact storage** — persistent key-value memory across conversations
- **Tool system** — config-driven skill registry loaded from `config/skills.yaml`
- **Sandbox execution** — Docker containers with `read_only`, `cap_drop=ALL`, `no-new-privileges`, `mem_limit`, `user=nobody`
- **HITL approval** — inline keyboard Approve/Deny with 120s timeout for high-stakes tools
- **Redaction** — secrets scrubbed at 3 points (inbound, tool results, outbound) using regex patterns + literal `.env` values
- **Content sanitizer** — HTML→Markdown, strips scripts/iframes/hidden content
- **Token guard** — max tool rounds and result truncation to prevent runaway loops
- **Audit logging** — all tool calls and approval decisions logged to SQLite
- **Scheduled jobs** — APScheduler-based autonomous loop (e.g. daily self-reflection)
- **Kill switch** — `/kill` clears memory, pauses jobs

### Built-in Skills

| Skill | Tools | Sandboxed | Approval |
|-------|-------|-----------|----------|
| Facts | `save_fact`, `get_fact`, `list_facts`, `delete_fact` | No | No |
| DateTime | `get_current_datetime` | No | No |
| Web Search | `web_search` (Brave API) | Yes | No |
| Google Drive | `gdrive_list_files`, `gdrive_create_file` | Yes | Yes |
| Email | `email_list_inbox`, `email_create_draft` | Yes | Yes |

## Prerequisites

- Python 3.10+
- Docker (for sandboxed skills)
- [Ollama](https://ollama.com) installed and running (`ollama serve`)
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))

## Setup

### 1. Clone and install

```bash
git clone <repo-url> senti
cd senti
pip install -e ".[dev]"
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your values:

```env
# Required
TELEGRAM_BOT_TOKEN=your-bot-token
ALLOWED_TELEGRAM_USER_IDS=123456789

# LLM
OLLAMA_HOST=http://localhost:11434
LLM_MODEL=ollama_chat/llama3

# Optional: Brave Search (for web_search tool)
BRAVE_API_KEY=your-brave-api-key

# Optional: Google Drive
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REFRESH_TOKEN=...

# Optional: Email
IMAP_HOST=imap.gmail.com
IMAP_USER=you@gmail.com
IMAP_PASSWORD=app-password
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
```

### 3. Install and start Ollama

Senti expects a running Ollama instance — it does **not** manage Ollama for you.
Install Ollama from [ollama.com](https://ollama.com), then:

```bash
ollama serve          # start the server (if not already running)
ollama pull llama3    # pull the model set in LLM_MODEL
```

Senti checks Ollama reachability on startup. If it can't connect you'll see:

```
ERROR: Ollama is not reachable at http://localhost:11434.
Please install Ollama (https://ollama.com) and start it with 'ollama serve'.
```

Set `OLLAMA_HOST` in `.env` if Ollama runs on a different address.

### 4. Build sandbox images (if using sandboxed skills)

```bash
make sandbox-build
```

### 5. Run

```bash
# Direct
python -m senti

# Or via Make
make run

# Or via Docker Compose (includes Ollama)
make docker-up
```

## After Starting

Once Senti is running (via `make run`, `python -m senti`, or `make docker-up`) you interact with it entirely through Telegram.

### Verify it's working

1. Open Telegram and find your bot (the one whose token you put in `.env`).
2. Send `/start`. You should get a greeting back.
3. Send `/status` to confirm the model and skills are loaded:
   ```
   Model: ollama_chat/llama3
   Memory: active
   Skills: 10 loaded
   Scheduler: active
   ```
4. Send a plain message like "Hello, what can you do?" — the bot should reply via the LLM.

If the bot doesn't respond, check the logs:

```bash
# Direct run — logs print to the console

# Docker Compose
docker compose logs -f senti
```

Common issues:
- **Bot not responding at all** — verify `TELEGRAM_BOT_TOKEN` is correct and the bot is not running elsewhere (only one process can poll a bot token).
- **"Ollama is not reachable"** — Ollama isn't running. Start it with `ollama serve`.
- **Messages ignored, no error** — your Telegram user ID is not in `ALLOWED_TELEGRAM_USER_IDS`. Send a message to [@userinfobot](https://t.me/userinfobot) to find your ID.

### Try the tools

Ask Senti to use its skills in natural language:

```
You: Remember that my birthday is March 15th.
Senti: ✓ Saved: birthday = March 15th

You: When is my birthday?
Senti: Your birthday is March 15th.

You: What time is it?
Senti: It is 2026-02-08 14:32:07 UTC (Saturday).

You: Search for the latest news about AI agents.
Senti: (runs web_search in a sandbox container, returns results)
```

For skills that require approval (Google Drive, Email), Senti will show an inline keyboard:

```
Senti: ⚠️ Approval required for: gdrive_create_file
       Arguments: {"name": "notes.txt", "content": "..."}
       [Approve] [Deny]
```

The tool only executes after you tap **Approve**. If you don't respond within 120 seconds, it times out.

### Manage the bot

Use commands to control Senti's state:

```
/reset    — clear your conversation history (start fresh)
/facts    — list everything Senti remembers about you
/status   — check model, skills, and scheduler state
/jobs     — see scheduled jobs and their next run time
/pause    — pause the scheduler (stops autonomous jobs)
/resume   — resume the scheduler
/kill     — emergency stop: clears memory, pauses all jobs
```

### Persistent data

All runtime data is stored in `data/` (gitignored):

- `data/senti.db` — SQLite database (conversations, facts, audit log)
- `data/logs/senti.log` — rotating JSON log file

To start completely fresh, run `make clean` or delete the `data/` directory.

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Greeting message |
| `/help` | List available commands |
| `/reset` | Clear conversation history |
| `/facts` | List all stored facts |
| `/status` | Show system status (model, skills, scheduler) |
| `/jobs` | List scheduled jobs |
| `/pause` | Pause the scheduler |
| `/resume` | Resume the scheduler |
| `/kill` | Emergency stop: clears memory, pauses all jobs |

## Configuration

### `config/personality.md`

System prompt that defines Senti's behavior and personality. Edit this to customize how the assistant responds.

### `config/skills.yaml`

Declares all skills with their module paths, sandbox settings, and approval flags. To add a new skill:

```yaml
skills:
  my_skill:
    description: "What the skill does"
    module: "senti.skills.builtin.my_skill"
    class_name: "MySkill"
    sandboxed: false
    requires_approval: false
```

### `config/redaction_patterns.yaml`

Regex patterns for scrubbing sensitive data (emails, phone numbers, API keys, etc.) from all text flowing through the system.

### `config/schedules.yaml`

Cron-based scheduled jobs. Currently supports `self_reflect` which sends a synthetic message through the orchestrator on a schedule.

## Project Structure

```
senti/
├── config/              # Personality, skills, redaction, schedules
├── src/senti/
│   ├── gateway/         # Telegram bot, filters, HITL approval
│   ├── controller/      # Orchestrator, LLM client, tool router, redaction
│   ├── memory/          # SQLite database, conversation buffer, fact store
│   ├── sandbox/         # Docker container executor, network policies
│   ├── skills/          # Base class, registry, built-in skills
│   ├── scheduler/       # APScheduler engine, job definitions
│   └── security/        # Content sanitizer, audit logging
├── sandbox_images/      # Dockerfiles for sandboxed skill containers
├── tests/
└── data/                # Runtime: senti.db, logs/ (gitignored)
```

## Security Design

**Sandbox isolation:** Sandboxed skills run in Docker containers with:
- `read_only` filesystem
- `cap_drop=ALL` (no Linux capabilities)
- `no-new-privileges` security option
- `mem_limit=128m`, `cpu_quota=50%`
- `user=nobody`
- `network_mode=none` by default (allowlisted per-skill)
- `/tmp` as noexec tmpfs

**Docker-out-of-Docker (DooD):** The host Docker socket is mounted into the Senti container. Sandbox containers are siblings, not nested. This avoids privileged DinD mode.

**Sandbox protocol:** `JSON in (stdin) → run.py → JSON out (stdout)`. Simple, testable, language-agnostic.

**Redaction at 3 points:** Inbound user messages, tool results, and outbound LLM responses. Automatically detects literal `.env` secret values in addition to regex patterns.

**HITL via asyncio.Future:** Tool execution awaits a Future that resolves when the user clicks Approve/Deny on the Telegram inline keyboard. 120-second timeout.

## Development

```bash
# Install with dev dependencies
make dev

# Run tests
make test

# Lint
make lint

# Auto-format
make format

# Clean runtime data
make clean
```

### Adding a New Skill

1. Create `src/senti/skills/builtin/my_skill.py` extending `BaseSkill`
2. Implement `name`, `get_tool_definitions()`, and `execute()`
3. Add an entry to `config/skills.yaml`
4. If sandboxed, create `sandbox_images/my_skill/run.py` and `Dockerfile`

### Running with Docker Compose

Ollama must already be running on the host — `docker compose` does **not** start it.

```bash
# Build everything
make docker-build
make sandbox-build

# Start Senti (connects to host Ollama via host networking)
make docker-up

# Stop
make docker-down
```
### Observing logs
```bash
docker compose logs -f senti
```