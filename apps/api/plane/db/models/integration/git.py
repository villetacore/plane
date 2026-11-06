# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.db import models
from django.db.models import Q

from plane.db.models.project import ProjectBaseModel


class GitConnection(ProjectBaseModel):
    """A Git repository whose webhook events are linked to this project's work items."""

    class Provider(models.TextChoices):
        GITHUB = "github", "GitHub"
        GITLAB = "gitlab", "GitLab"
        GITEA = "gitea", "Gitea"

    provider = models.CharField(max_length=20, choices=Provider.choices)
    repository_url = models.CharField(max_length=2000)
    # Encrypted with plane.license.utils.encryption; signature checks need the original value.
    webhook_secret = models.TextField()
    merged_state = models.ForeignKey(
        "db.State", on_delete=models.SET_NULL, null=True, blank=True, related_name="git_connections"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Git Connection"
        verbose_name_plural = "Git Connections"
        db_table = "git_connections"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["project", "provider", "repository_url"],
                condition=Q(deleted_at__isnull=True),
                name="git_connection_unique_project_provider_repository_when_not_deleted",
            )
        ]

    def __str__(self):
        return f"{self.provider} {self.repository_url}"
