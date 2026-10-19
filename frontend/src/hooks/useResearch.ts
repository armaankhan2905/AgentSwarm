import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, api } from '../lib/api';
import { isActive, mergeEvents } from '../lib/model';
import { streamEvents } from '../lib/stream';
import type { Session, ResearchEvent } from '../types';

export function useResearch(id: string) {
  const [session, setSession] = useState<Session | null>(null);
  const [events, setEvents] = useState<ResearchEvent[]>([]);
  const [error, setError] = useState('');
  const [streamStatus, setStreamStatus] = useState('connecting');
  const refreshRef = useRef<() => Promise<void>>(async () => {});
  const refresh = useCallback(() => refreshRef.current(), []);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    let cursor: string | number = 0;
    let snapshotTimer: ReturnType<typeof setTimeout> | undefined;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    let active = false;
    let initialized = false;
    let fetching = false;
    let refreshQueued = false;
    let connecting = false;

    setSession(null);
    setEvents([]);
    setError('');
    setStreamStatus('connecting');

    const schedule = () => {
      if (!snapshotTimer) {
        snapshotTimer = setTimeout(() => {
          snapshotTimer = undefined;
          void load();
        }, 350);
      }
    };

    const accept = (event: ResearchEvent) => {
      if (event.session_id && event.session_id !== id) return;
      if (Number.isFinite(Number(event.id)) && Number.isFinite(Number(cursor))) {
        cursor = Math.max(Number(cursor), Number(event.id));
      } else {
        cursor = event.id;
      }
      setEvents(old => mergeEvents(old, [event]));
      schedule();
    };

    const connect = async (attempt = 0): Promise<void> => {
      if (signal.aborted || connecting) return;
      connecting = true;
      try {
        await streamEvents(id, cursor, signal, accept, () => setStreamStatus('live'));
      } catch (e) {
        if (!signal.aborted && e instanceof ApiError && (e.status === 401 || e.status === 403)) {
          setStreamStatus('authentication required');
          active = false;
          connecting = false;
          return;
        }
      } finally {
        connecting = false;
      }
      if (signal.aborted) return;
      void load();
      setStreamStatus(active ? 'reconnecting' : 'recorded');
      if (active) retryTimer = setTimeout(() => void connect(attempt + 1), Math.min(15000, 1000 * 2 ** Math.min(attempt, 4)));
    };

    const startStream = () => {
      if (signal.aborted || connecting || !active) return;
      clearTimeout(retryTimer);
      retryTimer = undefined;
      setStreamStatus('connecting');
      void connect();
    };

    async function load(reconnect = true) {
      if (fetching || signal.aborted) {
        if (fetching) refreshQueued = true;
        return;
      }
      fetching = true;
      const wasActive = active;
      try {
        const value = await api.session(id, signal);
        if (!signal.aborted) {
          setSession(value);
          setError('');
          active = isActive(value.status);
          if (initialized && !wasActive && active) startStream();
        }
      } catch (e) {
        if (!signal.aborted) setError((e as Error).message);
      } finally {
        fetching = false;
        if (refreshQueued && !signal.aborted) {
          refreshQueued = false;
          void load();
        }
      }
      if (!reconnect) return;
    }

    refreshRef.current = () => load(true);

    void (async () => {
      await load(false);
      try {
        const persisted = await api.events(id, signal);
        for (const event of persisted) accept(event);
      } catch (e) {
        if (!signal.aborted) setStreamStatus(`Event replay unavailable: ${(e as Error).message}`);
      }
      initialized = true;
      if (!signal.aborted && active) startStream();
    })();

    const poll = setInterval(() => {
      if (active) void load();
    }, 12000);
    return () => {
      controller.abort();
      clearInterval(poll);
      clearTimeout(snapshotTimer);
      clearTimeout(retryTimer);
      refreshRef.current = async () => {};
    };
  }, [id]);

  return { session, events, error, streamStatus, refresh };
}
