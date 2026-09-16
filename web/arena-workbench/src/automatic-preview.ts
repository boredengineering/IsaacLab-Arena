import { useEffect, useLayoutEffect, useRef, useState } from 'react';

export const AUTOMATIC_PREVIEW_LIMIT = 3;
export const AUTOMATIC_PREVIEW_DEBOUNCE_MS = 1500;
export const AUTOMATIC_PREVIEW_INTERVAL_MS = 10_000;

/** Tab-local consent and budget: never persisted, replayed, or reset by an edit. */
export function useAutomaticPreview({ identity, ready, busy, blocked, request, submit, active = true, owner = '' }: {
  owner?: string;
  active?: boolean;
  identity: string | null;
  ready: boolean;
  busy: boolean;
  blocked: boolean;
  request: Record<string, unknown>;
  submit: (request: Record<string, unknown>, canDispatch: () => boolean) => Promise<unknown>;
}) {
  const [enabled, setOn] = useState(false);
  const [count, setCount] = useState(0);
  const [halted, setHalted] = useState(false);
  const [inFlight, setInFlight] = useState(false);
  const seen = useRef(new Set<string>());
  const lastAt = useRef(-Infinity);
  const flight = useRef(false);
  const generation = useRef(0);
  const activeNow = useRef(active);
  if (activeNow.current !== active) { activeNow.current = active; generation.current++; }
  const consentOwner = useRef(owner);
  if (consentOwner.current !== owner) { consentOwner.current = owner; generation.current++; }
  const [enabledOwner, setEnabledOwner] = useState(owner);
  useLayoutEffect(() => () => { generation.current++; }, []);
  const requestText = JSON.stringify(request);
  const candidate = JSON.stringify([identity, requestText, ready]);
  const candidateNow = useRef(candidate);
  if (candidateNow.current !== candidate) { candidateNow.current = candidate; generation.current++; }
  const send = useRef(submit);
  send.current = submit;

  function setEnabled(next: boolean) {
    generation.current++;
    if (next && !activeNow.current) return;
    setOn(next);
    setEnabledOwner(owner);
    if (next) {
      seen.current = new Set(identity ? [identity] : []);
      setCount(0);
      setHalted(false);
      // Do not reset lastAt: rapidly toggling consent cannot evade the rate limit.
    }
  }
  useEffect(() => {
    setOn(false);
  }, [active, owner]);
  useEffect(() => {
    setCount(0);
    setHalted(false);
    seen.current = new Set();
  }, [owner]);
  useEffect(() => {
    if (!active || !enabled || enabledOwner !== owner || halted || blocked || !ready || busy || inFlight || !identity
      || seen.current.has(identity) || count >= AUTOMATIC_PREVIEW_LIMIT) return;
    const frozen = JSON.parse(requestText) as Record<string, unknown>;
    const epoch = generation.current;
    const timer = setTimeout(() => {
      if (!activeNow.current || flight.current || epoch !== generation.current) return;
      flight.current = true;
      seen.current.add(identity);
      lastAt.current = Date.now();
      setCount((value) => value + 1); // Attempts consume budget, including ambiguous failures.
      setInFlight(true);
      void send.current(frozen, () => activeNow.current && epoch === generation.current).catch(() => {
        if (epoch === generation.current) setHalted(true);
      }).finally(() => { flight.current = false; setInFlight(false); });
    }, Math.max(AUTOMATIC_PREVIEW_DEBOUNCE_MS, lastAt.current + AUTOMATIC_PREVIEW_INTERVAL_MS - Date.now()));
    return () => clearTimeout(timer);
  }, [active, owner, enabledOwner, enabled, halted, blocked, ready, busy, inFlight, identity, count, requestText]);
  return { enabled: active && enabled && enabledOwner === owner, setEnabled, count, halted, inFlight };
}
