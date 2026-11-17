export interface ConversationMessage {
  role: "user" | "assistant" | "system";
  content: string;
  metadata?: {
    function_called?: string;
    function_result?: Record<string, unknown>;
    record_saved?: boolean;
  };
}

export interface NativeHistoryOwner {
  sessionId: string;
  sourceKey: string;
  generation: number;
}

export interface NativeServerHistoryCursor extends NativeHistoryOwner {
  messageCount: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function assistantMessages(value: unknown): Array<Pick<ConversationMessage, "role" | "content">> {
  if (!Array.isArray(value)) return [];
  return value.slice(-100).flatMap((entry) => {
    if (!isRecord(entry) || entry.role !== "assistant" ||
        typeof entry.content !== "string" || entry.content.length > 16_384) return [];
    return [{ role: "assistant" as const, content: entry.content }];
  });
}

function sameOwner(cursor: NativeServerHistoryCursor, owner: NativeHistoryOwner): boolean {
  return cursor.sessionId === owner.sessionId &&
    cursor.sourceKey === owner.sourceKey &&
    cursor.generation === owner.generation;
}

export function initializeNativeAssistantHistory(
  history: unknown,
  owner: NativeHistoryOwner,
): { messages: Array<Pick<ConversationMessage, "role" | "content">>; cursor: NativeServerHistoryCursor } {
  const messageCount = Array.isArray(history) ? history.length : 0;
  return {
    messages: assistantMessages(history),
    cursor: { ...owner, messageCount },
  };
}

export function appendNativeAssistantHistory(
  history: unknown,
  cursor: NativeServerHistoryCursor | null,
  owner: NativeHistoryOwner,
): { messages: Array<Pick<ConversationMessage, "role" | "content">>; cursor: NativeServerHistoryCursor | null } {
  if (!cursor || !sameOwner(cursor, owner) || !Array.isArray(history) ||
      history.length < cursor.messageCount) {
    return { messages: [], cursor };
  }

  const nextCursor = { ...cursor, messageCount: history.length };
  return {
    messages: assistantMessages(history.slice(cursor.messageCount)),
    cursor: nextCursor,
  };
}

export function mergeNativeAssistantTail(
  current: ConversationMessage[],
  assistantTail: Array<Pick<ConversationMessage, "role" | "content">>,
): ConversationMessage[] {
  return [...current, ...assistantTail];
}
