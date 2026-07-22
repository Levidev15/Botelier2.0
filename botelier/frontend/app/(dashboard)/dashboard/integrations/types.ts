export interface AccountSecret {
  id: string;
  key: string;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export interface RequiredField {
  key: string;
  label: string;
  type: string;
  placeholder?: string;
  description?: string;
  required: boolean;
  options?: string[];
  option_labels?: Record<string, string>;
  show_when?: Record<string, string>;
}

export interface IntegrationType {
  id: string;
  slug: string;
  name: string;
  description: string;
  logo_url: string | null;
  provider: string;
  auth_type: string;
  documentation_url: string | null;
  is_enabled: boolean;
  required_fields: RequiredField[];
  endpoint_count: number;
  origin?: string;
}

export interface AccountIntegration {
  id: string;
  integration_type_id: string;
  integration_slug: string;
  integration_name: string;
  connection_name: string | null;
  status: string;
  connected_at: string | null;
  last_sync_at: string | null;
  last_error: string | null;
}

export interface MCPTool {
  name: string;
  description: string;
  parameters: {
    type: string;
    properties: Record<string, unknown>;
    required: string[];
  };
  source: string;
}

export interface MCPConnection {
  id: string;
  account_id: string;
  name: string;
  description: string | null;
  transport_type: string;
  server_url: string;
  auth_type: string;
  status: string;
  last_connected_at: string | null;
  last_error: string | null;
  is_active: boolean;
  discovered_tools: MCPTool[];
  created_at: string;
  updated_at: string | null;
}

export interface IntegrationStats {
  total_calls: number;
  successful_calls: number;
  failed_calls: number;
  last_called_at: string | null;
  last_error: string | null;
}

// ---- API Builder (Universal API Adapter) ----

export interface ImportableIntegrationType {
  id: string;
  slug: string;
  name: string;
  source_type: string;
  spec_version: string | null;
  endpoint_count: number;
  origin: string;
  auth_type: string;
  required_fields: RequiredField[];
}

export interface OperationVariable {
  name: string;
  type: string;
  description?: string;
  required?: boolean;
  ownership?: string;
  enum?: string[];
  default?: string;
}

export interface OperationPolicy {
  id: string;
  operation_id: string;
  enabled: boolean;
  risk_level: string | null;
  confirm_required: boolean;
  approval_required: boolean;
  max_amount: number | null;
  max_executions_per_conv: number | null;
  allowed_channels: string[] | null;
  response_size_bytes: number;
  redact_field_patterns: string[] | null;
  test_status: string;
  tested_at: string | null;
  test_passed: boolean | null;
  test_error: string | null;
}

export interface Operation {
  id: string;
  name: string;
  method: string;
  path: string;
  summary?: string;
  description?: string;
  risk_level?: string;
  variables?: OperationVariable[];
  policy: OperationPolicy | null;
  is_published: boolean;
  action_id: string | null;
}

export interface ToolSet {
  id: string;
  name: string;
  description: string | null;
}
