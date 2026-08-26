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

/**
 * `connecting` is a real state, not a cosmetic one. The API's event source yields nothing until
 * its fifteen second keepalive, so the response headers are not flushed and `onopen` does not
 * fire until the first ping. Reporting that as "disconnected" told an operator the stream was
 * broken every time they loaded a page.
 */
export type StreamState = "connecting" | "connected" | "disconnected";

const listeners = new Set<Listener>();
let source: EventSource | null = null;
let streamState: StreamState = "connecting";
const connectionListeners = new Set<(state: StreamState) => void>();

function setStreamState(state: StreamState) {
  streamState = state;
  connectionListeners.forEach((listener) => listener(state));
}

function ensureSource() {
  if (source) return;
  source = new EventSource("/api/stream");
  source.onopen = () => setStreamState("connected");
  source.onerror = () => setStreamState("disconnected");
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

export function useStreamState(): StreamState {
  const [state, setState] = useState<StreamState>(streamState);
  useEffect(() => {
    ensureSource();
    connectionListeners.add(setState);
    return () => {
      connectionListeners.delete(setState);
    };
  }, []);
  return state;
}

/** Kept for callers that only need the boolean. */
export function useStreamConnected(): boolean {
  return useStreamState() === "connected";
}
