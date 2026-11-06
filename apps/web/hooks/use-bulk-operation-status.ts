/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { EIssuesStoreType } from "@plane/types";
// hooks
import { useIssueStoreType } from "@/hooks/use-issue-layout-store";

/** Archived work items are read-only and drafts have no bulk endpoints, so selection is off in those views. */
export const useBulkOperationStatus = () => {
  const storeType = useIssueStoreType();
  return storeType !== EIssuesStoreType.ARCHIVED && storeType !== EIssuesStoreType.WORKSPACE_DRAFT;
};
