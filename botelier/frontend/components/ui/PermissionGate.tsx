"use client";

import React from "react";
import { ShieldOff } from "lucide-react";
import { usePermissions } from "@/lib/auth/usePermissions";
import type { UserPermissions } from "@/lib/auth/types";

interface PermissionGateProps {
  resource: string;
  action: string;
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

export function PermissionGate({ resource, action, children, fallback }: PermissionGateProps) {
  const { can, loading, isPlatformAdmin } = usePermissions();

  if (loading) return null;

  if (isPlatformAdmin || can(resource as keyof UserPermissions, action)) {
    return <>{children}</>;
  }

  if (fallback !== undefined) {
    return <>{fallback}</>;
  }

  return null;
}

export function AccessDeniedPage({ message = "You don't have permission to view this page." }: { message?: string }) {
  return (
    <div className="h-full flex items-center justify-center">
      <div className="text-center space-y-4">
        <div className="flex justify-center">
          <div className="p-4 rounded-full bg-red-500/10 border border-red-500/20">
            <ShieldOff className="h-10 w-10 text-red-400" />
          </div>
        </div>
        <h2 className="text-xl font-semibold text-gray-200">Access Denied</h2>
        <p className="text-gray-400 max-w-sm">{message}</p>
      </div>
    </div>
  );
}

export function usePagePermission(resource: string, action: string) {
  const perms = usePermissions();
  return {
    ...perms,
    hasAccess: perms.isPlatformAdmin || perms.can(resource as keyof UserPermissions, action),
  };
}
