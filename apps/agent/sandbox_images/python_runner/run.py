"""Python execution sandbox runner.

Protocol: SENTI_INPUT env var (JSON) → process → JSON on stdout.
Supports: run_python (arbitrary code), run_user_skill (user-defined tool).
"""

import io
import json
import os
import sys
import traceback

MAX_OUTPUT_CHARS = 8_000
MAX_CODE_CHARS = 10_000


def _clean_env():
    """Wipe ALL environment variables before executing user code."""
    for key in list(os.environ.keys()):
        del os.environ[key]


def do_run_python(args: dict) -> str:
    """Execute arbitrary Python code, capturing stdout/stderr."""
    code = args.get("code", "")
    if not code:
        return "No code provided."
    if len(code) > MAX_CODE_CHARS:
        return f"Code too long ({len(code)} chars, max {MAX_CODE_CHARS})."

    _clean_env()

    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    old_stdout, old_stderr = sys.stdout, sys.stderr

    try:
        sys.stdout = stdout_capture
        sys.stderr = stderr_capture
        namespace = {"__builtins__": __builtins__}
        exec(code, namespace)
    except Exception:
        traceback.print_exc(file=stderr_capture)
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    out = stdout_capture.getvalue()
    err = stderr_capture.getvalue()

    result = ""
    if out:
        result += out
    if err:
        result += ("\n" if result else "") + f"STDERR:\n{err}"
    if not result:
        result = "(no output)"

    if len(result) > MAX_OUTPUT_CHARS:
        result = result[:MAX_OUTPUT_CHARS] + "\n...[output truncated]..."

    return result


def do_run_user_skill(args: dict) -> str:
    """Execute a user-defined skill's run() function."""
    code = args.get("code", "")
    arguments = args.get("arguments", {})

    if not code:
        return "No skill code provided."
    if len(code) > MAX_CODE_CHARS:
        return f"Skill code too long ({len(code)} chars, max {MAX_CODE_CHARS})."

    _clean_env()

    namespace = {"__builtins__": __builtins__}
    try:
        exec(code, namespace)
    except Exception:
        return f"Skill code error:\n{traceback.format_exc()}"

    if "run" not in namespace or not callable(namespace["run"]):
        return "Skill code must define a callable 'run' function."

    stdout_capture = io.StringIO()
    old_stdout = sys.stdout

    try:
        sys.stdout = stdout_capture
        result = namespace["run"](arguments)
    except Exception:
        return f"Skill execution error:\n{traceback.format_exc()}"
    finally:
        sys.stdout = old_stdout

    printed = stdout_capture.getvalue()

    # Prefer return value, fall back to stdout
    if result is not None:
        output = str(result)
    elif printed:
        output = printed
    else:
        output = "(no output)"

    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + "\n...[output truncated]..."

    return output


def main() -> None:
    raw = os.environ.get("SENTI_INPUT", "{}")
    request = json.loads(raw)
    function = request.get("function", "")
    args = request.get("arguments", {})

    if function == "run_python":
        result = do_run_python(args)
    elif function == "run_user_skill":
        result = do_run_user_skill(args)
    else:
        result = f"Unknown function: {function}"

    json.dump({"result": result}, sys.stdout)


if __name__ == "__main__":
    main()
