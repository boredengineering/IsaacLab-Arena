import { useEffect, useRef, useState } from 'react';

export const AUTOMATIC_PREVIEW_LIMIT = 3;
export const AUTOMATIC_PREVIEW_DEBOUNCE_MS = 1500;
export const AUTOMATIC_PREVIEW_INTERVAL_MS = 10_000;

/** Tab-local consent and budget: never persisted, replayed, or reset by an edit. */
export function useAutomaticPreview({ identity, ready, busy, blocked, request, submit }: {
  identity: string | null;
  ready: boolean;
  busy: boolean;
  blocked: boolean;
  request: Record<string, unknown>;
  submit: (request: Record<string, unknown>) => Promise<unknown>;
}) {
  const [enabled, setOn] = useState(false);
  const [count, setCount] = useState(0);
  const [halted, setHalted] = useState(false);
  const [inFlight, setInFlight] = useState(false);
  const seen = useRef(new Set<string>());
  const lastAt = useRef(-Infinity);
  const flight = useRef(false);
  const generation = useRef(0);
  const requestText = JSON.stringify(request);
  const send = useRef(submit);
  send.current = submit;

  function setEnabled(next: boolean) {
    generation.current++;
    setOn(next);
    if (next) {
      seen.current = new Set(identity ? [identity] : []);
      setCount(0);
      setHalted(false);
      // Do not reset lastAt: rapidly toggling consent cannot evade the rate limit.
    }
  }
  useEffect(() => {
    if (!enabled || halted || blocked || !ready || busy || inFlight || !identity
      || seen.current.has(identity) || count >= AUTOMATIC_PREVIEW_LIMIT) return;
    const frozen = JSON.parse(requestText) as Record<string, unknown>;
    const epoch = generation.current;
    const timer = setTimeout(() => {
      if (flight.current || epoch !== generation.current) return;
      flight.current = true;
      seen.current.add(identity);
      lastAt.current = Date.now();
      setCount((value) => value + 1); // Attempts consume budget, including ambiguous failures.
      setInFlight(true);
      void send.current(frozen).catch(() => {
        if (epoch === generation.current) setHalted(true);
      }).finally(() => { flight.current = false; setInFlight(false); });
    }, Math.max(AUTOMATIC_PREVIEW_DEBOUNCE_MS, lastAt.current + AUTOMATIC_PREVIEW_INTERVAL_MS - Date.now()));
    return () => clearTimeout(timer);
  }, [enabled, halted, blocked, ready, busy, inFlight, identity, count, requestText]);
  return { enabled, setEnabled, count, halted, inFlight };
}
