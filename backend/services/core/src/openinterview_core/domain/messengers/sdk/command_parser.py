"""Channel-agnostic command grammar.

Recognized commands (case-insensitive, leading slash optional):

    /link <token>                   Bind this remote user to an app account
    /chat                           Enter general chat mode (workspace-wide)
    /mentor [project_name]          Start (or resume) a mentor session
    /interview [resume-or-project] [level]
                                    Start an interviewer session
                                      - default: most recent resume, level=mid
                                      - target can be a resume filename / id
                                        or, with --project, a project name / id
                                      - level ∈ {junior, mid, senior, lead}
    /exit (alias /end /stop /quit)  Leave the current mode
    /status                         Show current session + project
    /help                           List commands
    /projects                       List user's projects
    /resumes                        List user's resumes
    /resume <id-or-name>            Show parsed resume detail
    /sessions                       List recent mentor + interview sessions
    /resume-session <id-prefix>     Resume a previous session by id prefix
    /whoami                         Show counts (projects, resumes, sessions)

Any input that doesn't match a command is treated as a plain message and
routed to the user's active session.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CommandKind = Literal[
    "link",
    "chat",
    "mentor",
    "interview",
    "end",
    "status",
    "help",
    "message",
    "projects",
    "resumes",
    "resume_show",
    "sessions",
    "resume_session",
    "whoami",
]

VALID_LEVELS = {"junior", "mid", "senior", "lead"}


@dataclass(slots=True)
class ParsedCommand:
    kind: CommandKind
    args: dict[str, str]
    raw: str


def parse(text: str) -> ParsedCommand:
    raw = text or ""
    stripped = raw.strip()
    if not stripped:
        return ParsedCommand(kind="message", args={}, raw=raw)

    body = stripped[1:] if stripped.startswith("/") else stripped
    parts = body.split()
    head = parts[0].lower() if parts else ""

    if head == "link":
        token = parts[1] if len(parts) > 1 else ""
        return ParsedCommand(
            kind="link", args={"token": token} if token else {}, raw=raw
        )

    if head == "chat":
        return ParsedCommand(kind="chat", args={}, raw=raw)

    if head == "projects":
        return ParsedCommand(kind="projects", args={}, raw=raw)

    if head == "resumes":
        return ParsedCommand(kind="resumes", args={}, raw=raw)

    if head == "resume":
        # /resume <id-or-name>  → resume_show
        # bare /resume          → also show resumes list (helpful default)
        if len(parts) > 1:
            return ParsedCommand(
                kind="resume_show",
                args={"target": " ".join(parts[1:]).strip()},
                raw=raw,
            )
        return ParsedCommand(kind="resumes", args={}, raw=raw)

    if head in ("sessions", "history"):
        return ParsedCommand(kind="sessions", args={}, raw=raw)

    # /resume-session <prefix>  — also accept "resumesession" / "resume_session"
    if head in ("resume-session", "resumesession", "resume_session"):
        target = " ".join(parts[1:]).strip() if len(parts) > 1 else ""
        return ParsedCommand(
            kind="resume_session",
            args={"target": target} if target else {},
            raw=raw,
        )

    if head in ("whoami", "me"):
        return ParsedCommand(kind="whoami", args={}, raw=raw)

    if head == "mentor":
        args: dict[str, str] = {}
        if len(parts) > 1:
            args["project"] = " ".join(parts[1:]).strip()
        return ParsedCommand(kind="mentor", args=args, raw=raw)

    if head == "interview":
        # Grammar (resume-first; /interview alone uses most recent resume):
        #   /interview                              → resume mode, latest resume, mid
        #   /interview <target>                     → resume mode, target=<target>, mid
        #   /interview <target> <level>             → resume mode, target=<target>, <level>
        #   /interview --project [<target>] [level] → project mode, same shape
        # The trailing token is treated as a level only when it matches one
        # of VALID_LEVELS; otherwise it's part of the target name.
        args: dict[str, str] = {}
        rest = parts[1:]
        # Detect "--project" flag.
        if rest and rest[0].lower() in ("--project", "-p"):
            args["scope"] = "project"
            rest = rest[1:]
        else:
            args["scope"] = "resume"

        # Strip a trailing level token if present.
        if rest and rest[-1].lower() in VALID_LEVELS:
            args["level"] = rest[-1].lower()
            rest = rest[:-1]
        else:
            args["level"] = "mid"

        if rest:
            args["target"] = " ".join(rest).strip()

        return ParsedCommand(kind="interview", args=args, raw=raw)

    if head in ("end", "exit", "stop", "quit"):
        return ParsedCommand(kind="end", args={}, raw=raw)
    if head == "status":
        return ParsedCommand(kind="status", args={}, raw=raw)
    if head == "help":
        return ParsedCommand(kind="help", args={}, raw=raw)

    # Stripped didn't actually start with "/", or didn't match any known
    # command — it's just a chat message.
    if not stripped.startswith("/"):
        return ParsedCommand(kind="message", args={}, raw=raw)
    return ParsedCommand(kind="help", args={"reason": f"unknown command '{head}'"}, raw=raw)


HELP_TEXT = (
    "Open Interview commands\n"
    "------------------------\n"
    "Modes\n"
    "  /chat                          General chat (full workspace access)\n"
    "  /mentor [project]              Mentor mode (project-scoped)\n"
    "  /interview [resume] [level]    Interviewer, resume-driven by default\n"
    "                                  · /interview                   (latest resume, mid)\n"
    "                                  · /interview ada.pdf senior\n"
    "                                  · /interview --project demo    (legacy single-project)\n"
    "  /exit                          Leave the current mode\n"
    "  /status                        Show what mode you're in\n"
    "\n"
    "Workspace\n"
    "  /projects                      List your projects\n"
    "  /resumes                       List your resumes\n"
    "  /resume <id-or-name>           Show resume detail\n"
    "  /sessions                      List recent sessions\n"
    "  /resume-session <id-prefix>    Resume a past session\n"
    "  /whoami                        Show counts\n"
    "\n"
    "Outside any mode, plain messages start /chat automatically.\n"
    "In groups, the bot only replies to commands or while a session is\n"
    "active — it never chimes in unprompted."
)
