"""Unit tests for the messenger command grammar."""
from __future__ import annotations

from openinterview_core.domain.messengers.sdk import command_parser as cp


def test_plain_message():
    p = cp.parse("hello there")
    assert p.kind == "message"
    assert p.args == {}


def test_link_with_token():
    p = cp.parse("/link abc-123")
    assert p.kind == "link"
    assert p.args["token"] == "abc-123"


def test_link_without_token():
    p = cp.parse("/link")
    assert p.kind == "link"
    assert p.args == {}


def test_mentor_no_project():
    p = cp.parse("/mentor")
    assert p.kind == "mentor"
    assert p.args == {}


def test_mentor_with_project():
    p = cp.parse("/mentor my cool app")
    assert p.kind == "mentor"
    assert p.args["project"] == "my cool app"


def test_interview_bare_uses_resume_default():
    # /interview alone → resume mode, latest resume, default level.
    p = cp.parse("/interview")
    assert p.kind == "interview"
    assert p.args == {"scope": "resume", "level": "mid"}


def test_interview_target_with_level():
    p = cp.parse("/interview ada.pdf senior")
    assert p.kind == "interview"
    assert p.args == {"scope": "resume", "target": "ada.pdf", "level": "senior"}


def test_interview_target_without_level_defaults_to_mid():
    p = cp.parse("/interview ada.pdf")
    assert p.kind == "interview"
    assert p.args == {"scope": "resume", "target": "ada.pdf", "level": "mid"}


def test_interview_non_level_trailing_token_stays_in_target():
    # "wizard" is not a recognised level — it's now just part of the target
    # (resume filename / project name) rather than rejected outright.
    p = cp.parse("/interview demo wizard")
    assert p.kind == "interview"
    assert p.args == {"scope": "resume", "target": "demo wizard", "level": "mid"}


def test_interview_project_flag():
    p = cp.parse("/interview --project demo senior")
    assert p.kind == "interview"
    assert p.args == {"scope": "project", "target": "demo", "level": "senior"}


def test_interview_short_project_flag():
    p = cp.parse("/interview -p demo")
    assert p.kind == "interview"
    assert p.args == {"scope": "project", "target": "demo", "level": "mid"}


def test_end_status_help_aliases():
    assert cp.parse("/end").kind == "end"
    assert cp.parse("/status").kind == "status"
    assert cp.parse("/help").kind == "help"


def test_unknown_slash_command_help():
    p = cp.parse("/dance")
    assert p.kind == "help"
    assert "unknown command" in p.args["reason"]


def test_case_insensitive_command():
    assert cp.parse("/Mentor").kind == "mentor"
    assert cp.parse("/INTERVIEW demo MID").args["level"] == "mid"


def test_empty_input():
    assert cp.parse("").kind == "message"
    assert cp.parse("   ").kind == "message"


def test_chat_command():
    assert cp.parse("/chat").kind == "chat"


def test_exit_aliases():
    for s in ("/exit", "/end", "/stop", "/quit"):
        assert cp.parse(s).kind == "end", s


def test_projects_resumes_sessions():
    assert cp.parse("/projects").kind == "projects"
    assert cp.parse("/resumes").kind == "resumes"
    assert cp.parse("/sessions").kind == "sessions"
    assert cp.parse("/history").kind == "sessions"  # alias


def test_resume_show_with_target():
    p = cp.parse("/resume my-resume.pdf")
    assert p.kind == "resume_show"
    assert p.args["target"] == "my-resume.pdf"


def test_bare_resume_lists_resumes():
    # /resume with no args is the list, not a show.
    assert cp.parse("/resume").kind == "resumes"


def test_resume_session_command_aliases():
    p = cp.parse("/resume-session abc123")
    assert p.kind == "resume_session"
    assert p.args["target"] == "abc123"

    p2 = cp.parse("/resume_session abc123")
    assert p2.kind == "resume_session"

    # Bare /resume-session
    assert cp.parse("/resume-session").kind == "resume_session"
    assert cp.parse("/resume-session").args == {}


def test_whoami_alias():
    assert cp.parse("/whoami").kind == "whoami"
    assert cp.parse("/me").kind == "whoami"
