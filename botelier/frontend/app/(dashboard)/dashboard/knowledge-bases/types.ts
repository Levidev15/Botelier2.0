export interface KnowledgeBase {
  id: string;
  account_id: string;
  name: string;
  description: string | null;
  entry_count: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface Entry {
  id: string;
  knowledge_base_id: string;
  question: string;
  answer: string;
  category: string | null;
  expiration_date: string | null;
  is_expired: boolean;
  created_at: string;
  updated_at: string;
}

export interface ParsedRow {
  question: string;
  answer: string;
  category: string | null;
  expiration_date: string | null;
  isDuplicate: boolean;
}

export interface ImportResult {
  created: number;
  replaced: number;
  skipped: number;
  errors: number;
  error_details: string[];
}

export function parseCSVLine(line: string): string[] {
  const values: string[] = [];
  let current = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (inQuotes && line[i + 1] === '"') {
        current += '"';
        i++;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (ch === ',' && !inQuotes) {
      values.push(current.trim());
      current = "";
    } else {
      current += ch;
    }
  }
  values.push(current.trim());
  return values;
}

export function formatDate(dateString: string | null): string {
  if (!dateString) return "N/A";
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return "Just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;

  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: date.getFullYear() !== now.getFullYear() ? 'numeric' : undefined });
}
