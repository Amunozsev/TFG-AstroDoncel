import { useEffect, useState } from 'react';

export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || (import.meta.env.DEV ? 'http://localhost:8000' : window.location.origin)
).replace(/\/$/, '');

export const apiUrl = (path) => path.startsWith('http') ? path : `${API_BASE_URL}${path}`;

export async function apiFetch(path, options = {}) {
  const url = apiUrl(path);
  const headers = {
    ...(options.body && !(options.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}),
    ...(options.headers ?? {}),
  };

  const timeoutMs = options.timeoutMs ?? 45_000;
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(new Error('Request timed out')), timeoutMs);
  const abortFromCaller = () => controller.abort(options.signal?.reason);
  options.signal?.addEventListener('abort', abortFromCaller, { once: true });
  if (options.signal?.aborted) abortFromCaller();
  try {
    return await fetch(url, { ...options, headers, signal: controller.signal });
  } finally {
    window.clearTimeout(timeoutId);
    options.signal?.removeEventListener('abort', abortFromCaller);
  }
}

export function useArtifact(url) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!url) return undefined;
    const controller = new AbortController();
    queueMicrotask(async () => {
      if (controller.signal.aborted) return;
      setData(null);
      setError('');
      try {
        const response = await apiFetch(url, { signal: controller.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        if (!controller.signal.aborted) setData(payload);
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause.message);
      }
    });
    return () => controller.abort();
  }, [url]);

  return { data, error };
}
