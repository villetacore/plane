# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Verify and apply webhook events from GitHub, GitLab and Gitea/Forgejo."""

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from plane.bgtasks.issue_activities_task import issue_activity
from plane.db.models import GitConnection, Issue, IssueLink

MAX_LINK_TITLE_LENGTH = 255
CLOSED_STATE_GROUPS = ("completed", "cancelled")


@dataclass
class GitReference:
    """One commit or pull request mentioned by a webhook event."""

    kind: str  # "commit" | "pull_request"
    title: str
    url: str
    text: str  # where work item keys are looked for
    identifier: str
    merged: bool = False
    state: str = ""


@dataclass
class GitEvent:
    references: list = field(default_factory=list)


def verify_signature(provider, secret, headers, body):
    """Return whether the request was sent by someone who knows the connection's secret."""
    if provider == GitConnection.Provider.GITLAB:
        return hmac.compare_digest(headers.get("X-Gitlab-Token", "").encode(), secret.encode())

    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if provider == GitConnection.Provider.GITHUB:
        return hmac.compare_digest(headers.get("X-Hub-Signature-256", "").encode(), f"sha256={digest}".encode())
    if provider == GitConnection.Provider.GITEA:
        received = headers.get("X-Gitea-Signature") or headers.get("X-Forgejo-Signature") or ""
        return hmac.compare_digest(received.encode(), digest.encode())
    return False


def _commit_references(commits):
    references = []
    for commit in commits or []:
        sha = str(commit.get("id") or commit.get("sha") or "")
        message = str(commit.get("message") or "")
        url = commit.get("url") or ""
        if sha and url:
            summary = message.split("\n", 1)[0]
            references.append(
                GitReference(kind="commit", title=f"{sha[:7]} {summary}", url=url, text=message, identifier=sha)
            )
    return references


def _github_style_pull_request(payload):
    """GitHub and Gitea send the same pull request shape."""
    pull_request = payload.get("pull_request") or {}
    number = pull_request.get("number") or payload.get("number")
    url = pull_request.get("html_url")
    if not number or not url:
        return []
    title = str(pull_request.get("title") or "")
    branch = str((pull_request.get("head") or {}).get("ref") or "")
    merged = bool(pull_request.get("merged"))
    return [
        GitReference(
            kind="pull_request",
            title=f"PR #{number}: {title}",
            url=url,
            text="\n".join([title, str(pull_request.get("body") or ""), branch]),
            identifier=str(number),
            merged=merged and payload.get("action") == "closed",
            state="merged" if merged else str(pull_request.get("state") or ""),
        )
    ]


def _gitlab_merge_request(payload):
    attributes = payload.get("object_attributes") or {}
    number = attributes.get("iid")
    url = attributes.get("url")
    if not number or not url:
        return []
    title = str(attributes.get("title") or "")
    return [
        GitReference(
            kind="pull_request",
            title=f"MR !{number}: {title}",
            url=url,
            text="\n".join(
                [title, str(attributes.get("description") or ""), str(attributes.get("source_branch") or "")]
            ),
            identifier=str(number),
            merged=attributes.get("action") == "merge",
            state=str(attributes.get("state") or ""),
        )
    ]


def parse_event(provider, headers, payload):
    """Return the references in an event, or None for event types Plane does not use."""
    if not isinstance(payload, dict):
        return None
    if provider == GitConnection.Provider.GITLAB:
        event_type = headers.get("X-Gitlab-Event", "")
        if event_type == "Push Hook":
            return GitEvent(_commit_references(payload.get("commits")))
        if event_type == "Merge Request Hook":
            return GitEvent(_gitlab_merge_request(payload))
        return None

    if provider == GitConnection.Provider.GITHUB:
        event_type = headers.get("X-GitHub-Event", "")
    else:
        event_type = headers.get("X-Gitea-Event") or headers.get("X-Forgejo-Event") or ""
    if event_type == "push":
        return GitEvent(_commit_references(payload.get("commits")))
    if event_type == "pull_request":
        return GitEvent(_github_style_pull_request(payload))
    return None


def find_sequence_ids(text, project_identifier):
    """Find work item numbers for this project, e.g. WEB-12 in "fix/web-12-login"."""
    pattern = rf"(?<![A-Za-z0-9_-]){re.escape(project_identifier)}-(\d+)\b"
    # sequence_id is a 32-bit column, so a longer number can never match a work item.
    return {int(number) for number in re.findall(pattern, text, flags=re.IGNORECASE) if len(number) <= 9}


def _upsert_link(connection, issue, reference, origin, epoch):
    title = reference.title[:MAX_LINK_TITLE_LENGTH]
    metadata = {"source": "git", "provider": connection.provider, "kind": reference.kind, "state": reference.state}
    link = IssueLink.objects.filter(issue=issue, url=reference.url).first()
    if link:
        if link.title != title or link.metadata != metadata:
            link.title = title
            link.metadata = metadata
            link.save(update_fields=["title", "metadata", "updated_at"])
        return

    link = IssueLink.objects.create(
        issue=issue, project_id=issue.project_id, title=title, url=reference.url, metadata=metadata
    )
    if connection.created_by_id:
        issue_activity.delay(
            type="link.activity.created",
            requested_data=json.dumps({"id": str(link.id), "url": reference.url, "title": title}),
            actor_id=str(connection.created_by_id),
            issue_id=str(issue.id),
            project_id=str(issue.project_id),
            current_instance=None,
            epoch=epoch,
            notification=False,
            origin=origin,
        )


def _apply_merged_state(connection, issue, origin, epoch):
    merged_state = connection.merged_state
    if not merged_state or issue.state_id == merged_state.id:
        return
    if issue.state and issue.state.group in CLOSED_STATE_GROUPS:
        return

    previous_state_id = issue.state_id
    issue.state = merged_state
    issue.save()
    if connection.created_by_id:
        issue_activity.delay(
            type="issue.activity.updated",
            requested_data=json.dumps({"state_id": str(merged_state.id)}),
            actor_id=str(connection.created_by_id),
            issue_id=str(issue.id),
            project_id=str(issue.project_id),
            current_instance=json.dumps({"state_id": str(previous_state_id) if previous_state_id else None}),
            epoch=epoch,
            notification=True,
            origin=origin,
        )


def apply_event(connection, event, origin=None):
    """Link the event's commits and pull requests to work items; return how many links were touched."""
    epoch = int(timezone.now().timestamp())
    identifier = connection.project.identifier
    linked = 0
    for reference in event.references:
        if not reference.url.startswith(("https://", "http://")):
            continue
        sequence_ids = find_sequence_ids(reference.text, identifier)
        if not sequence_ids:
            continue
        issues = Issue.issue_objects.filter(project_id=connection.project_id, sequence_id__in=sequence_ids)
        with transaction.atomic():
            for issue in issues.select_related("state"):
                _upsert_link(connection, issue, reference, origin, epoch)
                if reference.merged:
                    _apply_merged_state(connection, issue, origin, epoch)
                linked += 1
    return linked
