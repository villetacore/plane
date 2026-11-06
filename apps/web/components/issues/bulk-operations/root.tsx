/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo, useState } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// plane imports
import { Button } from "@makeplane/propel/components/button";
import { CalendarOutline } from "@makeplane/propel/icons";
import { ConfirmDialog } from "@plane/blocks/dialog";
import { DateSelect } from "@plane/blocks/property-select";
import { setToast } from "@plane/blocks/toast";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import type { TBulkIssueProperties, TIssuePriorities } from "@plane/types";
import { cn, renderFormattedPayloadDate } from "@plane/utils";
// components
import { LabelSelect } from "@/components/dropdowns/label/label-select";
import { MemberSelect } from "@/components/dropdowns/member/member-select";
import { PrioritySelect } from "@/components/dropdowns/priority/priority-select";
import { StateSelect } from "@/components/dropdowns/state/state-select";
// hooks
import { useMultipleSelectStore } from "@/hooks/store/use-multiple-select-store";
import { useUserPermissions } from "@/hooks/store/user";
import { useIssuesStore } from "@/hooks/use-issue-layout-store";
import type { TSelectionHelper } from "@/hooks/use-multiple-select";

type Props = {
  className?: string;
  selectionHelpers: TSelectionHelper;
};

const BULK_ERROR_KEYS: Record<number, string> = {
  4091: "invalid_archive_state_group",
  4100: "invalid_issue_start_date",
  4101: "invalid_issue_start_date",
  4102: "invalid_issue_target_date",
};

export const IssueBulkOperationsRoot = observer(function IssueBulkOperationsRoot(props: Props) {
  const { className, selectionHelpers } = props;
  // router
  const { workspaceSlug } = useParams();
  // translation
  const { t } = useTranslation();
  // store hooks
  const { isSelectionActive, selectedEntityIds, clearSelection } = useMultipleSelectStore();
  const { issues: issuesStore, issueMap } = useIssuesStore();
  const { allowPermissions } = useUserPermissions();
  // states
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isDeleteOpen, setIsDeleteOpen] = useState(false);
  const [pendingAssigneeIds, setPendingAssigneeIds] = useState<string[]>([]);
  const [pendingLabelIds, setPendingLabelIds] = useState<string[]>([]);
  // derived values
  const slug = workspaceSlug?.toString() ?? "";
  const issueIdsByProject = useMemo(() => {
    const grouped: Record<string, string[]> = {};
    selectedEntityIds.forEach((issueId) => {
      const projectId = issueMap?.[issueId]?.project_id;
      if (projectId) (grouped[projectId] ??= []).push(issueId);
    });
    return grouped;
  }, [issueMap, selectedEntityIds]);
  const projectIds = Object.keys(issueIdsByProject);
  const singleProjectId = projectIds.length === 1 ? projectIds[0] : undefined;
  const allowedInAllProjects = (roles: EUserPermissions[]) =>
    projectIds.length > 0 &&
    projectIds.every((projectId) => allowPermissions(roles, EUserPermissionsLevel.PROJECT, slug, projectId));
  const canEdit = allowedInAllProjects([EUserPermissions.ADMIN, EUserPermissions.MEMBER]);
  const canDelete = allowedInAllProjects([EUserPermissions.ADMIN]);

  if (!isSelectionActive || selectionHelpers.isSelectionDisabled) return null;

  /** Runs one request per project, so a mixed selection in a workspace view still works. */
  const runForEachProject = async (
    operation: (projectId: string, issueIds: string[]) => Promise<unknown>,
    successKey: string
  ) => {
    setIsSubmitting(true);
    try {
      await Promise.all(Object.entries(issueIdsByProject).map(([projectId, ids]) => operation(projectId, ids)));
      setToast({ type: "success", title: t(successKey) });
      clearSelection();
    } catch (error) {
      const errorKey = BULK_ERROR_KEYS[(error as { error_code?: number } | undefined)?.error_code ?? -1];
      setToast({
        type: "error",
        title: t(
          errorKey ? `bulk_operations.error_details.${errorKey}.title` : "bulk_operations.toolbar.update_failed"
        ),
        message: errorKey ? t(`bulk_operations.error_details.${errorKey}.message`) : undefined,
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleUpdate = (properties: Partial<TBulkIssueProperties>) =>
    runForEachProject(
      (projectId, issueIds) => issuesStore.bulkUpdateProperties(slug, projectId, { issue_ids: issueIds, properties }),
      "bulk_operations.toolbar.updated"
    );

  const handleAssigneesClose = () => {
    if (!pendingAssigneeIds.length) return;
    void handleUpdate({ assignee_ids: pendingAssigneeIds });
    setPendingAssigneeIds([]);
  };

  const handleLabelsClose = () => {
    if (!pendingLabelIds.length) return;
    void handleUpdate({ label_ids: pendingLabelIds });
    setPendingLabelIds([]);
  };

  return (
    <div className={cn("sticky bottom-0 left-0 z-[2] grid min-h-20 place-items-center px-3.5 py-2", className)}>
      <div
        role="toolbar"
        aria-label={t("bulk_operations.toolbar.label")}
        className="flex w-full flex-wrap items-center gap-2 rounded-lg border border-subtle bg-surface-1 px-3 py-2 shadow-raised-200"
      >
        <span className="text-body-xs-medium whitespace-nowrap text-primary">
          {t("bulk_operations.toolbar.selected", { count: selectedEntityIds.length })}
        </span>
        <Button
          variant="tertiary"
          size="sm"
          stretch="auto"
          label={t("bulk_operations.toolbar.clear_selection")}
          onClick={clearSelection}
        />
        {canEdit && (
          <>
            <div className="h-5 w-px bg-layer-3" aria-hidden />
            {singleProjectId ? (
              <>
                <StateSelect
                  projectId={singleProjectId}
                  value={null}
                  onChange={(stateId) => void handleUpdate({ state_id: stateId })}
                  placeholder={t("state")}
                  variant="pill-md"
                  disabled={isSubmitting}
                />
                <MemberSelect
                  projectId={singleProjectId}
                  value={pendingAssigneeIds}
                  onChange={setPendingAssigneeIds}
                  onClose={handleAssigneesClose}
                  placeholder={t("assignees")}
                  multiple
                  variant="pill-md"
                  disabled={isSubmitting}
                />
                <LabelSelect
                  projectId={singleProjectId}
                  value={pendingLabelIds}
                  onChange={setPendingLabelIds}
                  onClose={handleLabelsClose}
                  placeholder={t("labels")}
                  variant="pill-md"
                  disabled={isSubmitting}
                />
              </>
            ) : (
              <span className="text-caption-sm-regular text-tertiary">
                {t("bulk_operations.toolbar.single_project_hint")}
              </span>
            )}
            <PrioritySelect
              value={undefined}
              onChange={(priority: TIssuePriorities) => void handleUpdate({ priority })}
              variant="pill-md"
              disabled={isSubmitting}
            />
            <DateSelect
              value={null}
              onChange={(date) => void handleUpdate({ start_date: date ? renderFormattedPayloadDate(date) : null })}
              placeholder={t("start_date")}
              icon={<CalendarOutline />}
              variant="pill-md"
              disabled={isSubmitting}
            />
            <DateSelect
              value={null}
              onChange={(date) => void handleUpdate({ target_date: date ? renderFormattedPayloadDate(date) : null })}
              placeholder={t("due_date")}
              icon={<CalendarOutline />}
              variant="pill-md"
              disabled={isSubmitting}
            />
            <div className="ml-auto flex items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                stretch="auto"
                label={t("archive")}
                disabled={isSubmitting}
                onClick={() =>
                  void runForEachProject(
                    async (projectId, issueIds) => issuesStore.archiveBulkIssues?.(slug, projectId, issueIds),
                    "bulk_operations.toolbar.archived"
                  )
                }
              />
              {canDelete && (
                <Button
                  variant="danger"
                  size="sm"
                  stretch="auto"
                  label={t("delete")}
                  disabled={isSubmitting}
                  onClick={() => setIsDeleteOpen(true)}
                />
              )}
            </div>
          </>
        )}
      </div>
      <ConfirmDialog
        isOpen={isDeleteOpen}
        isSubmitting={isSubmitting}
        handleClose={() => setIsDeleteOpen(false)}
        handleSubmit={async () => {
          await runForEachProject(
            (projectId, issueIds) => issuesStore.removeBulkIssues(slug, projectId, issueIds),
            "bulk_operations.toolbar.deleted"
          );
          setIsDeleteOpen(false);
        }}
        title={t("bulk_operations.toolbar.delete_title")}
        content={t("bulk_operations.toolbar.delete_message", { count: selectedEntityIds.length })}
      />
    </div>
  );
});
