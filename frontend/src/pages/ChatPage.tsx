import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import { ChatInput } from '../components/ChatInput';
import { LeadForm } from '../components/LeadForm';
import { MessageList } from '../components/MessageList';
import { SessionList } from '../components/SessionList';
import type { Message, Session } from '../types';

export function ChatPage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [suggestLead, setSuggestLead] = useState(false);
  const [showLeadForm, setShowLeadForm] = useState(false);
  const [aiMode, setAiMode] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);

  const refreshSessions = useCallback(async () => {
    try {
      const { sessions: list } = await api.listSessions();
      setSessions(list);
    } catch {
      /* backend может быть ещё не поднят */
    }
  }, []);

  const loadMessages = useCallback(async (sessionId: string) => {
    try {
      const { messages: msgs } = await api.getMessages(sessionId);
      setMessages(msgs);
    } catch {
      setMessages([]);
    }
  }, []);

  useEffect(() => {
    api.health().then((h) => setAiMode(`${h.ai_mode}/${h.ai_status}`)).catch(() => setAiMode('backend offline'));
    refreshSessions();
  }, [refreshSessions]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const selectSession = (id: string) => {
    setActiveId(id);
    setSuggestLead(false);
    setShowLeadForm(false);
    loadMessages(id);
  };

  const newDialog = async () => {
    try {
      const session = await api.createSession();
      setSessions((prev) => [{ ...session, message_count: 0 }, ...prev]);
      setActiveId(session.id);
      setMessages([]);
      setSuggestLead(false);
      setShowLeadForm(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось создать диалог');
    }
  };

  const send = async (text: string) => {
    // Если активного диалога нет — создаём новый (state обновится асинхронно,
    // поэтому используем id напрямую).
    let sid = activeId;
    if (!sid) {
      const session = await api.createSession();
      setSessions((prev) => [{ ...session, message_count: 0 }, ...prev]);
      setActiveId(session.id);
      sid = session.id;
    }

    setSending(true);
    setError('');
    setMessages((prev) => [
      ...prev,
      {
        id: -Date.now(),
        role: 'user',
        content: text,
        created_at: new Date().toISOString(),
      },
    ]);
    try {
      const resp = await api.chat(sid, text);
      setMessages((prev) => [
        ...prev,
        {
          id: -Date.now() - 1,
          role: 'assistant',
          content: resp.answer,
          sources: resp.sources,
          latency_ms: resp.latency_ms,
          ai_status: resp.ai_status,
          created_at: new Date().toISOString(),
        },
      ]);
      setSuggestLead(resp.suggest_lead);
      if (resp.suggest_lead) setShowLeadForm(true);
      refreshSessions();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка отправки');
    } finally {
      setSending(false);
    }
  };

  const submitLead = async (lead: { name: string; phone: string; company: string; session_id?: string }) => {
    await api.createLead(lead);
  };

  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3">
        <h1 className="text-lg font-bold text-slate-900">MTS EnergyTool AI Consultant</h1>
        <div className="flex items-center gap-3">
          {aiMode && <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">{aiMode}</span>}
          <button
            onClick={newDialog}
            className="rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
          >
            + Новый диалог
          </button>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        <aside className="w-64 shrink-0 border-r border-slate-200 bg-white">
          <SessionList sessions={sessions} activeId={activeId} onSelect={selectSession} />
        </aside>

        <main className="flex flex-1 flex-col">
          <div className="flex-1 overflow-y-auto bg-slate-50 p-4">
            <MessageList messages={messages} />
            {error && <div className="mt-2 text-sm text-red-600">{error}</div>}
            {showLeadForm && (
              <div className="mt-4 max-w-md">
                <LeadForm
                  sessionId={activeId}
                  onSubmit={submitLead}
                  onClose={() => setShowLeadForm(false)}
                />
              </div>
            )}
            {suggestLead && !showLeadForm && (
              <button
                onClick={() => setShowLeadForm(true)}
                className="mt-4 rounded-lg border border-blue-300 bg-blue-50 px-3 py-1.5 text-sm text-blue-700 hover:bg-blue-100"
              >
                Оформить заявку менеджеру
              </button>
            )}
            <div ref={bottomRef} />
          </div>
          <ChatInput onSend={send} disabled={sending} />
        </main>
      </div>
    </div>
  );
}
