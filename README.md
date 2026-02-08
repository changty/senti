# Senti (Sentinel-Agent)

A modular, security-first AI agent system. Senti connects a Telegram interface to LLMs (local via Ollama, or cloud providers like OpenAI, Gemini, Anthropic), with tool execution sandboxed in Docker containers and human-in-the-loop approval for high-stakes actions.

## Architecture

```
User → Telegram → AllowedUserFilter → Orchestrator
                                         ├── LLM (multi-provider via LiteLLM)
                                         │    Ollama / OpenAI / Gemini / Anthropic
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
- **Multi-model support** — switch between Ollama, OpenAI, Gemini, and Anthropic models at runtime via `/model`
- **Kill switch** — `/kill` clears memory, pauses jobs

### Built-in Skills

| Skill | Tools | Sandboxed | Approval |
|-------|-------|-----------|----------|
| Facts | `save_fact`, `get_fact`, `list_facts`, `delete_fact` | No | No |
| DateTime | `get_current_datetime` | No | No |
| Web Search | `web_search`, `web_fetch` (Brave API + page fetch with SSRF protection) | Yes | No |
| Google Drive | `gdrive_list_files`, `gdrive_create_file` | Yes | Yes |
| Email (Gmail) | `email_list_inbox`, `email_read`, `email_create_draft` | Yes | Yes |

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

# LLM — default Ollama, add API keys for cloud providers
OLLAMA_HOST=http://localhost:11434
LLM_MODEL=ollama_chat/llama3
OPENAI_API_KEY=
GEMINI_API_KEY=
ANTHROPIC_API_KEY=

# Optional: Brave Search (for web_search / web_fetch tools)
BRAVE_API_KEY=your-brave-api-key

# Optional: Google Drive (OAuth2)
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REFRESH_TOKEN=...

# Optional: Gmail (OAuth2 — scopes: gmail.readonly + gmail.compose)
GMAIL_REFRESH_TOKEN=
GMAIL_LABEL=Senti
```

Cloud provider API keys are only needed for the providers you want to use. You can switch between models at runtime with the `/model` command — see [Model Switching](#model-switching) below.

### 3. Install and start Ollama (for local models)

If you want to use local models, Senti expects a running Ollama instance — it does **not** manage Ollama for you. Install Ollama from [ollama.com](https://ollama.com), then:

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

> **Note:** If you only use cloud providers (OpenAI, Gemini, Anthropic) and change the default model in `config/models.yaml` accordingly, Ollama is not required.

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

# Or via Docker Compose
make docker-up
```

## After Starting

Once Senti is running (via `make run`, `python -m senti`, or `make docker-up`) you interact with it entirely through Telegram.

### Verify it's working

1. Open Telegram and find your bot (the one whose token you put in `.env`).
2. Send `/start`. You should get a greeting back.
3. Send `/status` to confirm the model and skills are loaded:
   ```
   Model: llama3 (ollama_chat/llama3)
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
/model    — list available models or switch: /model <name>
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
| `/model` | List models, or `/model <name>` to switch |
| `/reset` | Clear conversation history |
| `/facts` | List all stored facts |
| `/status` | Show system status (model, skills, scheduler) |
| `/jobs` | List scheduled jobs |
| `/pause` | Pause the scheduler |
| `/resume` | Resume the scheduler |
| `/kill` | Emergency stop: clears memory, pauses all jobs |

## Model Switching

Senti supports multiple LLM providers. Models are predefined in `config/models.yaml`:

```yaml
default: llama3

models:
  llama3:
    model: ollama_chat/llama3
    provider: ollama
    description: "Llama 3 (local, via Ollama)"

  gpt-4o-mini:
    model: gpt-4o-mini
    provider: openai
    description: "OpenAI GPT-4o Mini"

  gemini-flash:
    model: gemini/gemini-2.0-flash
    provider: gemini
    description: "Google Gemini 2.0 Flash"

  claude-sonnet:
    model: claude-sonnet-4-5-20250929
    provider: anthropic
    description: "Anthropic Claude Sonnet 4.5"
```

Switch models at runtime in Telegram:

```
/model                  — list all available models (active model marked)
/model gpt-4o-mini      — switch to GPT-4o Mini
/model gemini-flash     — switch to Gemini 2.0 Flash
/model llama3           — switch back to local Ollama
```

The `model` field uses [LiteLLM format](https://docs.litellm.ai/docs/providers). Add API keys for cloud providers in `.env`:

| Provider | Env variable | Model prefix |
|----------|-------------|--------------|
| Ollama | (none, uses `OLLAMA_HOST`) | `ollama_chat/` |
| OpenAI | `OPENAI_API_KEY` | (native model names) |
| Gemini | `GEMINI_API_KEY` | `gemini/` |
| Anthropic | `ANTHROPIC_API_KEY` | (native model names) |

To add a new model, add an entry to `config/models.yaml` — no code changes needed.

## Gmail Setup

Senti uses Gmail OAuth2 with minimal scopes (`gmail.readonly` + `gmail.compose`). It can only read emails in a designated label and create drafts — it never sends email.

### 1. Create OAuth credentials

1. Go to [Google Cloud Console → Credentials](https://console.cloud.google.com/apis/credentials)
2. Create an **OAuth 2.0 Client ID** (type: Desktop app)
3. Add `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` to your `.env`

### 2. Obtain a refresh token

```bash
python scripts/gmail_oauth.py
```

This opens your browser for Google sign-in, requests the two limited scopes, and prints the refresh token. Add it to `.env`:

```env
GMAIL_REFRESH_TOKEN=your-refresh-token-here
```

### 3. Create the Gmail label

Create a label named `Senti` (or whatever you set `GMAIL_LABEL` to) in Gmail. Senti can only read emails with this label and will only create drafts — never send.

## Configuration

### `config/personality.md`

System prompt that defines Senti's behavior and personality. Edit this to customize how the assistant responds.

### `config/models.yaml`

Predefined LLM models for runtime switching. See [Model Switching](#model-switching) above.

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

**Sandbox protocol:** JSON in via `SENTI_INPUT` env var → `run.py` → JSON out on stdout. API keys passed as separate env vars. Simple, testable, language-agnostic.

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