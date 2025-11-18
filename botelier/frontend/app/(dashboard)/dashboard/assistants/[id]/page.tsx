"use client";

import { useParams } from "next/navigation";
import AssistantConfigForm from "@/components/forms/AssistantConfigForm";

export default function AssistantDetailPage() {
  const params = useParams();
  const assistantId = params.id as string;
  
  return <AssistantConfigForm mode="edit" assistantId={assistantId} />;
}
