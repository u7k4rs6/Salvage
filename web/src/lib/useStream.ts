import { useEffect, useRef, useState } from "react";

// The event names the API will send. Mirrors salvage/api/stream.py, which refuses anything else.
export const EVENT_NAMES = [
  "attempt",
  "incident.opened",
  "incident.updated",
  "incident.closed",
  "action.executed",
  "action.refused",
  "escalation.opened",
  "escalation.decided",
  "ledger.appended",
  "sim.tick",
  "sim.finished",
] as const;

export type EventName = (typeof EVENT_NAMES)[number];

export interface StreamEvent {
  name: EventName;
  data: Record<string, unknown>;
  at: number;
}

/**
 * One EventSource for the whole console, shared by every page through this module.
 *
 * A per-page connection would open and close a stream on every navigation and the API would fan
 * out to queues nobody is reading. One connection, many subscribers.
 */
type Listener = (event: StreamEvent) => void;

const listeners = new Set<Listener>();
let source: EventSource | null = null;
let connected = false;
const connectionListeners = new Set<(state: boolean) => void>();

function setConnected(state: boolean) {
  connected = state;
  connectionListeners.forEach((listener) => listener(state));
}

function ensureSource() {
  if (source) return;
  source = new EventSource("/api/stream");
  source.onopen = () => setConnected(true);
  source.onerror = () => setConnected(false);
  EVENT_NAMES.forEach((name) => {
    source!.addEventListener(name, (raw) => {
      let data: Record<string, unknown> = {};
      try {
        data = JSON.parse((raw as MessageEvent).data || "{}");
      } catch {
        data = {};
      }
      const event: StreamEvent = { name, data, at: Date.now() };
      listeners.forEach((listener) => listener(event));
    });
  });
}

/** Subscribe to named events. `onEvent` is held in a ref so a page can pass an inline function. */
export function useStream(names: readonly EventName[], onEvent: (event: StreamEvent) => void) {
  const handler = useRef(onEvent);
  handler.current = onEvent;
  const wanted = names.join(",");

  useEffect(() => {
    ensureSource();
    const listener: Listener = (event) => {
      if (wanted.split(",").includes(event.name)) handler.current(event);
    };
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, [wanted]);
}

export function useStreamConnected(): boolean {
  const [state, setState] = useState(connected);
  useEffect(() => {
    ensureSource();
    connectionListeners.add(setState);
    return () => {
      connectionListeners.delete(setState);
    };
  }, []);
  return state;
}
