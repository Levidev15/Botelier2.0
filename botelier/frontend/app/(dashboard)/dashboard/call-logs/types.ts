export interface CallLeg {
  id: string;
  leg_number: number;
  leg_type: string;
  call_sid: string | null;
  participant: string | null;
  participant_name: string | null;
  status: string;
  started_at: string | null;
  ended_at: string | null;
  duration_seconds: number | null;
}

export interface TranscriptEntry {
  role: string;
  content?: string;
  text?: string;
  timestamp?: string;
  interrupted?: boolean;
}

export interface CallLog {
  id: string;
  account_id: string;
  reference_id: string | null;
  call_sid: string;
  phone_number_id: string | null;
  assistant_id: string | null;
  caller_number: string | null;
  to_number: string | null;
  status: string;
  outcome: string;
  started_at: string | null;
  answered_at: string | null;
  ended_at: string | null;
  duration_seconds: number;
  has_transfer: boolean;
  flow_id: string | null;
  flow_name: string | null;
  recording_url: string | null;
  transcript: TranscriptEntry[] | null;
  legs: CallLeg[];
  assistant_name: string | null;
  phone_number_display: string | null;
  disposition_id: string | null;
  disposition_name: string | null;
  disposition_color: string | null;
  ai_summary: string | null;
  tool_name: string | null;
  acw_resolution: string | null;
  acw_quality_score: number | null;
  acw_skip_reason?: string | null;
  caller_spoke?: boolean | null;
  ended_early: boolean;
}

export interface FilterOptions {
  assistants: Array<{ id: string; name: string }>;
  phone_numbers: Array<{ id: string; number: string; name: string | null }>;
  statuses: string[];
  dispositions: Array<{ id: string; name: string; color: string }>;
  resolution_options: string[];
}
