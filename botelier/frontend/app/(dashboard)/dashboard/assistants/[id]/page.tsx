"use client";

import { useParams } from "next/navigation";
import AssistantConfigForm from "@/components/forms/AssistantConfigForm";
import { usePagePermission, AccessDeniedPage } from "@/components/ui/PermissionGate";

export default function AssistantDetailPage() {
  const params = useParams();
  const assistantId = params.id as string;
  const { hasAccess, loading: permLoading } = usePagePermission("assistants", "view");

  if (permLoading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="animate-spin h-6 w-6 border-2 border-blue-500 border-t-transparent rounded-full" />
      </div>
    );
  }

  if (!hasAccess) {
    return <AccessDeniedPage message="You don't have permission to view this assistant." />;
  }

  return <AssistantConfigForm mode="edit" assistantId={assistantId} />;
}
