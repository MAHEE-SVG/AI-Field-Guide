"""GitHub catch-up digest workflow.

Lists pull requests merged since a given date and open pull requests still
waiting on review, then posts a digest as a Slack DM to the user who started
the run. Runs on behalf of the triggering user: GitHub and Slack credentials
resolve from that user's connector connections.
"""

import json
import re
from datetime import timedelta
from typing import Any

import pydantic
import mistralai.workflows as workflows
from mistralai.workflows import Depends
from mistralai.workflows.plugins.mistralai.connectors import (
    ToolCallClient,
    connector,
    uses_connectors,
)

MAX_PRS_PER_SECTION = 25

github_connector = connector("github_app")
slack_connector = connector("slack")

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class CatchupInput(pydantic.BaseModel):
    repo: str
    since: str


class PullRequestEntry(pydantic.BaseModel):
    number: int
    title: str
    url: str


class CatchupDigest(pydantic.BaseModel):
    repo: str
    since: str
    merged: list[PullRequestEntry]
    awaiting_review: list[PullRequestEntry]


def normalize_repo_handle(repo: str) -> str:
    handle = repo.strip()
    handle = re.sub(r"^https?://github\.com/", "", handle)
    handle = handle.removesuffix(".git").strip("/")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", handle):
        raise ValueError(f"Invalid repository handle: {repo!r} (expected 'owner/repo')")
    return handle


def validate_since_date(since: str) -> str:
    if not DATE_PATTERN.match(since.strip()):
        raise ValueError(f"Invalid date: {since!r} (expected 'YYYY-MM-DD')")
    return since.strip()


def extract_tool_payload(result: Any) -> Any:
    if isinstance(result, dict):
        structured = result.get("structuredContent")
        if structured is not None:
            return structured
        content = result.get("content")
        if isinstance(content, list) and content:
            texts = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            joined = "\n".join(text for text in texts if text)
            try:
                return json.loads(joined)
            except json.JSONDecodeError:
                return joined
    return result


def parse_pull_request_items(items: Any) -> list[PullRequestEntry]:
    if not isinstance(items, list):
        return []
    entries: dict[int, PullRequestEntry] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        number = item.get("number")
        title = item.get("title")
        url = item.get("html_url")
        if not isinstance(number, int) or not isinstance(title, str) or not isinstance(url, str):
            continue
        entries[number] = PullRequestEntry(number=number, title=title, url=url)
    return [entries[number] for number in sorted(entries)]


def format_pull_request_line(entry: PullRequestEntry) -> str:
    title = " ".join(entry.title.split())
    return f"• [{title} #{entry.number}]({entry.url})"


def format_section(title: str, entries: list[PullRequestEntry]) -> str:
    lines = [f"*{title} ({len(entries)})*"]
    if not entries:
        lines.append("_None_")
        return "\n".join(lines)
    for entry in entries[:MAX_PRS_PER_SECTION]:
        lines.append(format_pull_request_line(entry))
    remaining = len(entries) - MAX_PRS_PER_SECTION
    if remaining > 0:
        lines.append(f"_…and {remaining} more_")
    return "\n".join(lines)


def format_catchup_digest(digest: CatchupDigest) -> str:
    header = f"*GitHub catch-up for `{digest.repo}` — merged since {digest.since} and PRs waiting on review*"
    merged_section = format_section("Merged since " + digest.since, digest.merged)
    review_section = format_section("Waiting on review", digest.awaiting_review)
    return "\n\n".join([header, merged_section, review_section])


def extract_slack_user_id(payload: Any) -> str:
    if isinstance(payload, dict):
        user_id = payload.get("user_id") or payload.get("id")
        if isinstance(user_id, str) and user_id:
            return user_id
        payload = payload.get("result") or payload.get("content")
    if isinstance(payload, str):
        match = re.search(r"User ID:\s*(\S+)", payload)
        if match:
            return match.group(1)
    raise ValueError("Could not determine the Slack user ID for the current user")


@workflows.activity(start_to_close_timeout=timedelta(seconds=60))
async def search_merged_pull_requests(
    repo: str,
    since: str,
    github: ToolCallClient = Depends(github_connector),
) -> list[PullRequestEntry]:
    owner, name = repo.split("/", 1)
    result = await github.call_tool(
        "search_pull_requests",
        {
            "query": f"is:merged merged:>={since}",
            "owner": owner,
            "repo": name,
            "sort": "updated",
            "order": "desc",
            "perPage": 100,
            "fields": ["number", "title", "html_url"],
        },
    )
    payload = extract_tool_payload(result)
    return parse_pull_request_items(payload.get("items") if isinstance(payload, dict) else payload)


@workflows.activity(start_to_close_timeout=timedelta(seconds=60))
async def search_pull_requests_awaiting_review(
    repo: str,
    github: ToolCallClient = Depends(github_connector),
) -> list[PullRequestEntry]:
    owner, name = repo.split("/", 1)
    entries_by_number: dict[int, PullRequestEntry] = {}
    for review_state in ("review:required", "review:changes_requested"):
        result = await github.call_tool(
            "search_pull_requests",
            {
                "query": f"is:open {review_state}",
                "owner": owner,
                "repo": name,
                "sort": "updated",
                "order": "desc",
                "perPage": 100,
                "fields": ["number", "title", "html_url"],
            },
        )
        payload = extract_tool_payload(result)
        items = payload.get("items") if isinstance(payload, dict) else payload
        for entry in parse_pull_request_items(items):
            entries_by_number[entry.number] = entry
    return [entries_by_number[number] for number in sorted(entries_by_number)]


@workflows.activity(start_to_close_timeout=timedelta(seconds=60))
async def post_digest_to_slack(
    message: str,
    slack: ToolCallClient = Depends(slack_connector),
) -> str:
    profile_result = await slack.call_tool("slack_read_user_profile", {})
    user_id = extract_slack_user_id(extract_tool_payload(profile_result))
    send_result = await slack.call_tool(
        "slack_send_message",
        {"channel_id": user_id, "message": message},
    )
    payload = extract_tool_payload(send_result)
    if isinstance(payload, str) and payload:
        return payload
    return f"Digest sent to Slack DM for user {user_id}"


@workflows.workflow.define(
    name="github-catchup",
    workflow_display_name="GitHub Catch-up Digest",
    workflow_description=(
        "Lists pull requests merged since a given date and open pull requests "
        "waiting on review in a GitHub repository, then posts a digest with "
        "one line per PR to a Slack DM with the triggering user."
    ),
    on_behalf_of=True,
)
@uses_connectors(github_connector, slack_connector)
class GithubCatchupWorkflow:
    @workflows.workflow.entrypoint
    async def run(self, input: CatchupInput) -> str:
        repo = normalize_repo_handle(input.repo)
        since = validate_since_date(input.since)
        merged = await search_merged_pull_requests(repo=repo, since=since)
        awaiting_review = await search_pull_requests_awaiting_review(repo=repo)
        digest = CatchupDigest(
            repo=repo,
            since=since,
            merged=merged,
            awaiting_review=awaiting_review,
        )
        message = format_catchup_digest(digest)
        return await post_digest_to_slack(message=message)
