# Senti (Sentinel-Agent)

A modular, security-first AI agent system. Senti connects a Telegram interface to LLMs (local via Ollama, or cloud providers like OpenAI, Gemini, Anthropic), with tool execution sandboxed in Docker containers and human-in-the-loop approval for sensitive actions.

## Quick Start

```bash
git clone <repo-url> senti && cd senti
cd apps/agent
pip install -e ".[dev]"
cp .env.example .env          # edit with your values
make sandbox-build             # build Docker sandbox images
python3 -m senti               # start the bot
```

Open Telegram, find your bot, send `/start`. See [Agent Setup](#agent-setup) for full details.

## Architecture

```
User → Telegram → AllowedUserFilter → Orchestrator
                                         ├── LLM (multi-provider via LiteLLM)
                                         ├── Memory (SQLite + markdown files)
                                         ├── In-process skills (memory, datetime, scheduler, skillsmith)
                                         └── Sandboxed skills (search, gdrive, email, python)
                                              └── Docker containers (read-only, no caps, nobody user)
```

**Gateway → Controller → Sandbox** — the AI never has direct, unmediated access to the host.

### Message Flow

1. User sends a Telegram message (text or photo)
2. `AllowedUserFilter` checks the user ID whitelist
3. Orchestrator redacts inbound text, loads conversation history + relevant memories
4. LLM generates a response (optionally with tool calls)
5. Tool-call loop:
   - Check if the tool requires approval → HITL inline keyboard
   - Route: sandboxed → Docker container | in-process → direct call
   - Sanitize + redact tool result
   - Re-call LLM with results
6. Redact outbound response, save to conversation memory
7. Send response back to Telegram
8. Audit event logged to SQLite

## Features

- **Access control** — Telegram user ID whitelist
- **Conversation memory** — sliding window buffer (configurable, default 20 messages) persisted to SQLite
- **Rich memory system** — categorized memories (preference, fact, people, goal, general) with importance scoring, keyword search, and automatic context injection
- **Image understanding** — send photos to Senti and it will describe and reason about them
- **Python execution** — run arbitrary Python code in a sandboxed Docker container (numpy, pandas available)
- **Custom tools** — create, list, and delete reusable user-defined tools that persist across conversations
- **Tool system** — config-driven skill registry loaded from `config/skills.yaml`
- **Sandbox execution** — Docker containers with `read_only`, `cap_drop=ALL`, `no-new-privileges`, `mem_limit`, `user=nobody`
- **HITL approval** — inline keyboard Approve/Deny (+ Approve & Trust for user-created tools) with 120s timeout
- **Redaction** — secrets scrubbed at 3 points (inbound, tool results, outbound) using regex patterns + literal `.env` values
- **Content sanitizer** — HTML→Markdown, strips scripts/iframes/hidden content
- **Token guard** — max tool rounds and result truncation to prevent runaway loops
- **Usage tracking** — per-user token usage stats via `/usage`
- **Audit logging** — all tool calls and approval decisions logged to SQLite
- **Scheduled jobs** — APScheduler-based autonomous loop (e.g. daily self-reflection) + user-created cron jobs
- **Multi-model support** — switch between Ollama, OpenAI, Gemini, and Anthropic models at runtime via `/model`
- **Undo** — `/undo` removes the last conversation turn
- **Kill switch** — `/kill` clears memory, pauses jobs

### Skills

| Skill | Tools | Sandboxed | Approval |
|-------|-------|-----------|----------|
| Memory | `save_memory`, `search_memories`, `list_memories`, `update_memory`, `delete_memory` | No | No |
| DateTime | `get_current_datetime` | No | No |
| Scheduler | `create_scheduled_job`, `list_scheduled_jobs`, `delete_scheduled_job` | No | No |
| Skillsmith | `create_skill`, `list_user_skills`, `delete_skill` | No | `create_skill` only |
| Python | `run_python` | Yes | Yes |
| Web Search | `web_search`, `web_fetch` (Brave API + SSRF-protected page fetch) | Yes | No |
| Google Drive | `gdrive_list_files`, `gdrive_create_file` | Yes | Yes |
| Email (Gmail) | `email_list_inbox`, `email_read`, `email_create_draft` | Yes | Yes |

**User-created tools** (via Skillsmith) are also sandboxed and require approval. After clicking "Approve & Trust", a user tool runs without future prompts.

## Agent Setup

### 1. Install

```bash
cd apps/agent
pip install -e ".[dev]"
```

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Required
TELEGRAM_BOT_TOKEN=your-bot-token
ALLOWED_TELEGRAM_USER_IDS=123456789

# LLM — default Ollama, add API keys for cloud providers
OLLAMA_HOST=http://localhost:11434
LLM_MODEL=ollama_chat/llama3

# Cloud providers (optional — only needed for the ones you use)
OPENAI_API_KEY=
GEMINI_API_KEY=
ANTHROPIC_API_KEY=

# Brave Search (optional)
BRAVE_API_KEY=

# Google Drive (optional, OAuth2)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REFRESH_TOKEN=

# Gmail (optional, OAuth2 — scopes: gmail.readonly + gmail.compose)
GMAIL_REFRESH_TOKEN=
GMAIL_LABEL=Senti
```

### 3. LLM setup

**Local (Ollama):** Install from [ollama.com](https://ollama.com), then:

```bash
ollama serve          # start the server
ollama pull llama3    # pull the model set in LLM_MODEL
```

**Cloud-only:** If you only use cloud providers, change the default model in `config/models.yaml` and Ollama is not required.

### 4. Build sandbox images

```bash
make sandbox-build
```

This builds Docker images for web search, Google Drive, Gmail, and Python execution.

### 5. Run

```bash
python3 -m senti      # direct
make run               # via Make
```

Or from the repo root:

```bash
docker compose up -d   # via Docker Compose
```

## Usage

### Verify the agent is working

1. Open Telegram and find your bot.
2. Send `/start` — you should get a greeting.
3. Send `/status` to confirm skills are loaded.
4. Send a message like "Hello, what can you do?"

### Examples

```
You: Remember that my birthday is March 15th.
Senti: Saved to memory under "preference".

You: What time is it?
Senti: It is 2026-02-11 14:32 UTC.

You: Search for the latest news about AI agents.
Senti: (runs web_search → web_fetch in sandbox, returns summary)

You: Calculate the first 20 fibonacci numbers.
Senti: (requests approval → runs run_python in sandbox → returns output)

You: Create a tool that converts celsius to fahrenheit.
Senti: (requests approval → creates skill → registered for future use)

You: Convert 100 celsius.
Senti: (runs user skill → Approve / Deny / Approve & Trust)
```

### Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Greeting message |
| `/help` | List available commands |
| `/model` | List models, or `/model <name>` to switch |
| `/reset` | Clear conversation history |
| `/undo` | Remove last conversation turn |
| `/memories` | List stored memories |
| `/usage` | Token usage statistics |
| `/status` | System status (model, skills, scheduler) |
| `/jobs` | List scheduled jobs |
| `/pause` | Pause the scheduler |
| `/resume` | Resume the scheduler |
| `/kill` | Emergency stop: clears memory, pauses all jobs |

### Approval flow

Tools marked as requiring approval show an inline keyboard before executing:

```
Approval required: run_python

print("Hello, world!")

[Approve] [Deny]
```

User-created tools show a third button — **Approve & Trust** — which skips approval on future invocations of that tool.

## Model Switching

Models are defined in `config/models.yaml`. Switch at runtime:

```
/model                  — list all available models
/model gpt-4o-mini      — switch to GPT-4o Mini
/model gemini-flash     — switch to Gemini Flash
/model llama3           — switch back to local Ollama
```

The `model` field uses [LiteLLM format](https://docs.litellm.ai/docs/providers). To add a model, add an entry to `config/models.yaml` — no code changes needed.

| Provider | Env variable | Model prefix |
|----------|-------------|--------------|
| Ollama | (none, uses `OLLAMA_HOST`) | `ollama_chat/` |
| OpenAI | `OPENAI_API_KEY` | (native names) |
| Gemini | `GEMINI_API_KEY` | `gemini/` |
| Anthropic | `ANTHROPIC_API_KEY` | (native names) |

## Gmail Setup

Senti uses Gmail OAuth2 with minimal scopes (`gmail.readonly` + `gmail.compose`). It can only read emails in a designated label and create drafts — it never sends email.

1. Create OAuth credentials at [Google Cloud Console → Credentials](https://console.cloud.google.com/apis/credentials) (Desktop app type)
2. Run `python3 scripts/gmail_oauth.py` to get a refresh token
3. Create a Gmail label matching `GMAIL_LABEL` (default: "Senti")
4. Add credentials to `.env`

## Configuration

| File | Purpose |
|------|---------|
| `apps/agent/config/personality.md` | System prompt — personality, behavior, tool usage instructions |
| `apps/agent/config/models.yaml` | LLM model definitions for runtime switching |
| `apps/agent/config/skills.yaml` | Skill registry — modules, sandbox settings, approval flags |
| `apps/agent/config/redaction_patterns.yaml` | Regex patterns for scrubbing sensitive data |
| `apps/agent/config/schedules.yaml` | Cron-based scheduled jobs |

## Project Structure

```
senti/
├── apps/
│   └── agent/                        # Python Telegram bot
│       ├── config/                   # Personality, skills, models, redaction, schedules
│       ├── src/senti/
│       │   ├── gateway/              # Telegram bot, handlers, filters, HITL approval
│       │   ├── controller/           # Orchestrator, LLM client, tool router, redaction
│       │   ├── memory/               # SQLite database, conversation buffer, memory store
│       │   ├── sandbox/              # Docker container executor
│       │   ├── skills/               # Base class, registry, user skill store, built-in skills
│       │   ├── scheduler/            # APScheduler engine, job store, job definitions
│       │   └── security/             # Content sanitizer, audit logging
│       ├── sandbox_images/           # Dockerfiles for sandboxed skill containers
│       ├── tests/
│       ├── data/                     # Runtime: senti.db, logs/, memories/ (gitignored)
│       ├── pyproject.toml
│       └── Makefile
│
├── docker-compose.yml
└── README.md
```

## Security

**Sandbox isolation:** All sandboxed skills run in Docker containers with:
- `read_only` filesystem, `cap_drop=ALL`, `no-new-privileges`
- `mem_limit=128m`, `cpu_quota=50%`, `user=nobody`
- `network_mode=none` by default (allowlisted per-skill)
- `/tmp` as noexec tmpfs
- Environment wiped before executing user code (python_runner)

**No secrets leak to user code:** The python sandbox receives no API keys. Environment variables are cleared before `exec()`.

**HITL:** Sensitive tool calls require explicit user approval via Telegram inline keyboard. User-created tools can be individually trusted after review.

**Redaction:** Secrets scrubbed at 3 points — inbound, tool results, outbound — using regex patterns and literal `.env` value detection.

**Docker-out-of-Docker (DooD):** Sandbox containers run as siblings via the host Docker socket, avoiding privileged DinD mode.

## Development

```bash
cd apps/agent
make dev              # install with dev dependencies
make test             # run tests
make lint             # ruff check
make format           # ruff auto-format
make clean            # remove runtime data
```

### Adding a built-in skill

1. Create `apps/agent/src/senti/skills/builtin/my_skill.py` extending `BaseSkill`
2. Implement `name`, `get_tool_definitions()`, and `execute()`
3. Add an entry to `apps/agent/config/skills.yaml`
4. If sandboxed, create `apps/agent/sandbox_images/my_skill/run.py` + `Dockerfile`

### Docker Compose

Ollama must already be running on the host.

```bash
cd apps/agent
make sandbox-build

# from repo root
docker compose build
docker compose up -d
docker compose logs -f senti
```
