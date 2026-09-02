"use client";

/**
 * Shared SMS Server-Sent Events context.
 *
 * Architecture: one EventSource per browser tab, shared by all consumers.
 *   - SMSStreamProvider opens the connection and fans out events to subscribers.
 *   - useSSEEvent() subscribes a component to a specific event type without
 *     opening a second connection.
 *
 * Compared to each component owning its own EventSource:
 *   - One TCP connection per tab instead of N.
 *   - One reconnect path, one token-read, one keepalive stream.
 *   - Badge badge counter and message list both react to the same event instantly.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
} from "react";
import { useAccountContext } from "@/lib/auth/useAccountContext";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type SSEHandler = (event: MessageEvent) => void;

interface SMSStreamContextValue {
  /** Register a handler for one SSE event type. Returns an unsubscribe fn. */
  subscribe: (eventType: string, handler: SSEHandler) => () => void;
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const SMSStreamContext = createContext<SMSStreamContextValue>({
  subscribe: () => () => {},
});

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

const SSE_EVENTS = [
  "new_message",
  "new_reply",
  "handoff_requested",
  "handler_changed",
] as const;

export function SMSStreamProvider({ children }: { children: React.ReactNode }) {
  const { accountId } = useAccountContext();

  // Map<eventType, Set<handler>> — mutated in place, never causes re-renders.
  const listenersRef = useRef<Map<string, Set<SSEHandler>>>(new Map());

  useEffect(() => {
    if (!accountId) return;

    const sseToken =
      typeof window !== "undefined"
        ? (window.localStorage.getItem("botelier_token") ?? "")
        : "";
    if (!sseToken) return;

    const es = new EventSource(
      `/api/sms/stream?account_id=${accountId}&token=${encodeURIComponent(sseToken)}`
    );

    // Build a dispatcher per event type that fans out to all registered handlers.
    // Typed as EventListener (takes Event) so addEventListener is happy; we cast
    // to MessageEvent inside because EventSource always fires MessageEvent for
    // named custom events.
    const dispatchers: Array<[string, EventListener]> = SSE_EVENTS.map((ev) => {
      const fn: EventListener = (event: Event) => {
        listenersRef.current
          .get(ev)
          ?.forEach((h) => h(event as MessageEvent));
      };
      es.addEventListener(ev, fn);
      return [ev, fn];
    });

    es.onerror = () => {
      console.debug("SMS SSE connection interrupted, reconnecting…");
    };

    return () => {
      dispatchers.forEach(([ev, fn]) => es.removeEventListener(ev, fn));
      es.close();
    };
  }, [accountId]);

  const subscribe = useCallback(
    (eventType: string, handler: SSEHandler): (() => void) => {
      if (!listenersRef.current.has(eventType)) {
        listenersRef.current.set(eventType, new Set());
      }
      listenersRef.current.get(eventType)!.add(handler);
      return () => {
        listenersRef.current.get(eventType)?.delete(handler);
      };
    },
    []
  );

  return (
    <SMSStreamContext.Provider value={{ subscribe }}>
      {children}
    </SMSStreamContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * Subscribe to one SSE event type for the lifetime of the calling component.
 *
 * The handler is always invoked with its latest closure — the subscription is
 * NOT torn down and recreated when the handler function identity changes across
 * re-renders. Pass any function; useSSEEvent keeps a ref to the latest version.
 */
export function useSSEEvent(eventType: string, handler: SSEHandler): void {
  const { subscribe } = useContext(SMSStreamContext);

  // Always store the latest handler so the registered "stable" function below
  // calls the current closure without needing to re-subscribe.
  const handlerRef = useRef<SSEHandler>(handler);
  useEffect(() => {
    handlerRef.current = handler;
  });

  useEffect(() => {
    const stable: SSEHandler = (event) => handlerRef.current(event);
    return subscribe(eventType, stable);
    // subscribe is stable (useCallback []); eventType is a string constant.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eventType, subscribe]);
}
