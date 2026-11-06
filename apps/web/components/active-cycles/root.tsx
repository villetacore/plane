/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import useSWR from "swr";
// plane imports
import { EmptyStateDetailed } from "@plane/blocks/empty-state";
import { Loader } from "@plane/blocks/skeleton";
import { useTranslation } from "@plane/i18n";
// components
import { ActiveCycleRoot } from "@/components/cycles/active-cycle/root";
// hooks
import { useCycle } from "@/hooks/store/use-cycle";
import { useProject } from "@/hooks/store/use-project";

export const WorkspaceActiveCyclesRoot = observer(function WorkspaceActiveCyclesRoot() {
  // router
  const { workspaceSlug } = useParams();
  const slug = workspaceSlug?.toString();
  // translation
  const { t } = useTranslation();
  // store hooks
  const { fetchWorkspaceActiveCycles } = useCycle();
  const { getProjectById } = useProject();
  // fetch
  const { data: cycles, isLoading } = useSWR(
    slug ? `WORKSPACE_ACTIVE_CYCLES_${slug}` : null,
    slug ? () => fetchWorkspaceActiveCycles(slug) : null,
    { revalidateOnFocus: false }
  );

  if (isLoading || !cycles || !slug) {
    return (
      <Loader className="flex flex-col gap-4 p-5">
        <Loader.Item height="180px" />
        <Loader.Item height="180px" />
      </Loader>
    );
  }

  if (cycles.length === 0) {
    return (
      <EmptyStateDetailed
        assetKey="cycle"
        title={t("workspace_empty_state.active_cycles.title")}
        description={t("workspace_empty_state.active_cycles.description")}
      />
    );
  }

  return (
    <div className="h-full w-full overflow-y-auto">
      {cycles.map((cycle) => (
        <section key={cycle.id} aria-label={cycle.name}>
          <h2 className="sticky top-0 z-[3] border-b border-subtle bg-layer-1 px-5 py-2 text-body-xs-medium text-secondary">
            {getProjectById(cycle.project_id)?.name}
          </h2>
          <ActiveCycleRoot workspaceSlug={slug} projectId={cycle.project_id} cycleId={cycle.id} showHeader={false} />
        </section>
      ))}
    </div>
  );
});
