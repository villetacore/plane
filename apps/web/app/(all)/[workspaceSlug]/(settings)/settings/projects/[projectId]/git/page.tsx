/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// plane imports
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
// components
import { NotAuthorizedView } from "@/components/auth-screens/not-authorized-view";
import { PageHead } from "@/components/core/page-title";
import { GitIntegrationRoot } from "@/components/project/settings/git-integration/root";
import { SettingsContentWrapper } from "@/components/settings/content-wrapper";
// hooks
import { useProject } from "@/hooks/store/use-project";
import { useUserPermissions } from "@/hooks/store/user";
// local imports
import type { Route } from "./+types/page";
import { GitIntegrationProjectSettingsHeader } from "./header";

function GitIntegrationSettingsPage({ params }: Route.ComponentProps) {
  const { workspaceSlug, projectId } = params;
  const { t } = useTranslation();
  // store hooks
  const { workspaceUserInfo, allowPermissions } = useUserPermissions();
  const { currentProjectDetails } = useProject();
  // derived values
  const isAdmin = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.PROJECT);
  const pageTitle = currentProjectDetails?.name
    ? `${currentProjectDetails.name} - ${t("project_settings.git_integration.heading")}`
    : undefined;

  if (workspaceUserInfo && !isAdmin) {
    return <NotAuthorizedView section="settings" isProjectView className="h-auto" />;
  }

  return (
    <SettingsContentWrapper header={<GitIntegrationProjectSettingsHeader />} hugging>
      <PageHead title={pageTitle} />
      <GitIntegrationRoot
        workspaceSlug={workspaceSlug}
        projectId={projectId}
        projectIdentifier={currentProjectDetails?.identifier ?? "WEB"}
      />
    </SettingsContentWrapper>
  );
}

export default observer(GitIntegrationSettingsPage);
