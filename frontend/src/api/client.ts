import type { ChatResponse, Lead, Message, Session } from '../types';

const BASE = '/api';

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const err = await resp.json();
      if (err?.detail) detail = String(err.detail);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json() as Promise<T>;
}

function withToken(path: string, token?: string): string {
  return token ? `${path}${path.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}` : path;
}

export const api = {
  health: () => request<{ status: string; ai_mode: string; ai_status: string }>('GET', '/health'),
  createSession: () => request<Session>('POST', '/sessions'),
  listSessions: () => request<{ sessions: Session[] }>('GET', '/sessions'),
  getMessages: (sessionId: string, token?: string) =>
    request<{ session_id: string; messages: Message[] }>(
      'GET',
      withToken(`/sessions/${sessionId}/messages`, token),
    ),
  deleteSession: (sessionId: string, token?: string) =>
    request<void>('DELETE', withToken(`/sessions/${sessionId}`, token)),
  chat: (sessionId: string, message: string, token?: string) =>
    request<ChatResponse>('POST', '/chat', {
      session_id: sessionId,
      message,
      session_token: token,
    }),
  createLead: (lead: {
    name: string;
    phone: string;
    company: string;
    session_id?: string;
    session_token?: string;
  }) => request<Lead>('POST', '/leads', lead),
};
