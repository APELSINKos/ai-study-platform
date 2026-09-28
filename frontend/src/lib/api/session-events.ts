type SessionExpiredListener = () => void;

const listeners = new Set<SessionExpiredListener>();

/** Runs the listener whenever a session is confirmed lost (a failed refresh). */
export function onSessionExpired(listener: SessionExpiredListener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function emitSessionExpired(): void {
  for (const listener of listeners) {
    listener();
  }
}
