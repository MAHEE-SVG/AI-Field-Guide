import pytest

from worker.workflows.github_catchup import (
    CatchupDigest,
    PullRequestEntry,
    extract_slack_user_id,
    extract_tool_payload,
    format_catchup_digest,
    normalize_repo_handle,
    parse_pull_request_items,
    validate_since_date,
)


class TestNormalizeRepoHandle:
    def test_plain_handle(self):
        assert normalize_repo_handle("owner/repo") == "owner/repo"

    def test_whitespace(self):
        assert normalize_repo_handle("  owner/repo ") == "owner/repo"

    def test_github_url(self):
        assert normalize_repo_handle("https://github.com/owner/repo") == "owner/repo"

    def test_git_suffix(self):
        assert normalize_repo_handle("owner/repo.git") == "owner/repo"

    def test_invalid_handle(self):
        with pytest.raises(ValueError):
            normalize_repo_handle("not-a-repo")


class TestValidateSinceDate:
    def test_valid_date(self):
        assert validate_since_date("2025-12-01") == "2025-12-01"

    def test_invalid_format(self):
        with pytest.raises(ValueError):
            validate_since_date("12/01/2025")


class TestExtractToolPayload:
    def test_structured_content(self):
        assert extract_tool_payload({"structuredContent": {"items": [1]}}) == {"items": [1]}

    def test_text_content_json(self):
        result = {"content": [{"type": "text", "text": '{"total_count": 2}'}]}
        assert extract_tool_payload(result) == {"total_count": 2}

    def test_text_content_plain(self):
        result = {"content": [{"type": "text", "text": "User ID: U123"}]}
        assert extract_tool_payload(result) == "User ID: U123"

    def test_passthrough(self):
        assert extract_tool_payload("raw") == "raw"


class TestParsePullRequestItems:
    def test_parses_items(self):
        items = [
            {"number": 2, "title": "Fix bug", "html_url": "https://github.com/o/r/pull/2"},
            {"number": 1, "title": "Add feature", "html_url": "https://github.com/o/r/pull/1"},
        ]
        entries = parse_pull_request_items(items)
        assert [entry.number for entry in entries] == [1, 2]
        assert entries[0].title == "Add feature"

    def test_skips_malformed_items(self):
        items = [
            {"number": "x", "title": "bad", "html_url": "u"},
            {"number": 3, "title": "good", "html_url": "https://github.com/o/r/pull/3"},
        ]
        entries = parse_pull_request_items(items)
        assert len(entries) == 1 and entries[0].number == 3

    def test_non_list(self):
        assert parse_pull_request_items(None) == []


class TestFormatCatchupDigest:
    def test_digest_with_entries(self):
        digest = CatchupDigest(
            repo="owner/repo",
            since="2025-12-01",
            merged=[
                PullRequestEntry(number=1, title="Add feature", url="https://github.com/o/r/pull/1")
            ],
            awaiting_review=[],
        )
        message = format_catchup_digest(digest)
        assert "`owner/repo`" in message
        assert "2025-12-01" in message
        assert "[Add feature #1](https://github.com/o/r/pull/1)" in message
        assert "_None_" in message

    def test_digest_empty(self):
        digest = CatchupDigest(repo="owner/repo", since="2025-12-01", merged=[], awaiting_review=[])
        message = format_catchup_digest(digest)
        assert "Merged since 2025-12-01 (0)" in message
        assert "Waiting on review (0)" in message


class TestExtractSlackUserId:
    def test_from_profile_text(self):
        text = "User ID: U0CJB7ZQDL1\nUsername: someone"
        assert extract_slack_user_id(text) == "U0CJB7ZQDL1"

    def test_from_dict(self):
        assert extract_slack_user_id({"user_id": "U42"}) == "U42"

    def test_missing(self):
        with pytest.raises(ValueError):
            extract_slack_user_id("no id here")
