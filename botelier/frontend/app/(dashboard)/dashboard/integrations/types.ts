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
