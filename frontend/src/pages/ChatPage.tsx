import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import { ChatInput } from '../components/ChatInput';
import { Header } from '../components/Header';
import { LeadForm } from '../components/LeadForm';
import { MessageBubble } from '../components/MessageBubble';
import { Sidebar } from '../components/Sidebar';
import { TypingIndicator } from '../components/TypingIndicator';
import { WelcomeScreen } from '../components/WelcomeScreen';
import type { Message, Session } from '../types';

interface LastAttempt {
  sid: string;
  text: string;
}

export function ChatPage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [sessionsError, setSessionsError] = useState('');
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [lastAttempt, setLastAttempt] = useState<LastAttempt | null>(null);
  const [suggestLead, setSuggestLead] = useState(false);
  const [showLeadModal, setShowLeadModal] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [showDebug, setShowDebug] = useState(() => localStorage.getItem('mts-show-debug') === '1');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sidebarMobileOpen, setSidebarMobileOpen] = useState(false);
  const [aiMode, setAiMode] = useState('');
  const [backendOnline, setBackendOnline] = useState(true);

  const activeIdRef = useRef<string | null>(null);
  const messagesRequestRef = useRef(0);
  const sendingRef = useRef(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    activeIdRef.current = activeId;
  }, [activeId]);

  useEffect(() => {
    localStorage.setItem('mts-show-debug', showDebug ? '1' : '0');
  }, [showDebug]);

  const loadSessions = useCallback(async (silent = false) => {
    if (!silent) {
      setSessionsLoading(true);
      setSessionsError('');
    }
    try {
      const { sessions: list } = await api.listSessions();
      setSessions(list);
      setBackendOnline(true);
    } catch (err) {
      if (!silent) {
        setSessionsError(err instanceof Error ? err.message : 'Не удалось загрузить диалоги');
      }
      if (err instanceof TypeError) setBackendOnline(false);
    } finally {
      if (!silent) setSessionsLoading(false);
    }
  }, []);

  const loadMessages = useCallback(async (sessionId: string) => {
    const requestId = ++messagesRequestRef.current;
    setMessagesLoading(true);
    setError('');
    try {
      const { messages: msgs } = await api.getMessages(sessionId);
      if (requestId === messagesRequestRef.current && activeIdRef.current === sessionId) {
        setMessages(msgs);
      }
    } catch (err) {
      if (requestId === messagesRequestRef.current && activeIdRef.current === sessionId) {
        setError(err instanceof Error ? err.message : 'Не удалось загрузить историю');
        setMessages([]);
      }
    } finally {
      if (requestId === messagesRequestRef.current) {
        setMessagesLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    api
      .health()
      .then((h) => {
        setAiMode(h.ai_mode);
        setBackendOnline(true);
      })
      .catch(() => {
        setAiMode('');
        setBackendOnline(false);
      });
    loadSessions();
  }, [loadSessions]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, sending]);

  const selectSession = useCallback(
    (id: string) => {
      activeIdRef.current = id;
      setActiveId(id);
      setSuggestLead(false);
      setShowLeadModal(false);
      setLastAttempt(null);
      setMessages([]);
      loadMessages(id);
    },
    [loadMessages],
  );

  const newDialog = useCallback(async () => {
    try {
      const session = await api.createSession();
      setSessions((prev) => [{ ...session, message_count: 0 }, ...prev]);
      activeIdRef.current = session.id;
      setActiveId(session.id);
      setMessages([]);
      setSuggestLead(false);
      setShowLeadModal(false);
      setLastAttempt(null);
      setError('');
      setSidebarMobileOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось создать диалог');
      if (err instanceof TypeError) setBackendOnline(false);
    }
  }, []);

  const performSend = useCallback(
    async (sid: string, text: string) => {
      if (sendingRef.current) return;
      sendingRef.current = true;
      const tempId = -Date.now() - Math.floor(Math.random() * 1000);
      setSending(true);
      setError('');
      setLastAttempt(null);

      if (activeIdRef.current === sid) {
        setMessages((prev) => [
          ...prev,
          { id: tempId, role: 'user', content: text, created_at: new Date().toISOString() },
        ]);
      }

      try {
        const resp = await api.chat(sid, text);
        if (activeIdRef.current === sid) {
          setMessages((prev) => [
            ...prev,
            {
              id: -Date.now() - Math.floor(Math.random() * 1000),
              role: 'assistant',
              content: resp.answer,
              sources: resp.sources,
              latency_ms: resp.latency_ms,
              ai_status: resp.ai_status,
              created_at: new Date().toISOString(),
            },
          ]);
          setSuggestLead(resp.suggest_lead);
        }
        loadSessions(true);
      } catch (err) {
        if (activeIdRef.current === sid) {
          setMessages((prev) => prev.filter((m) => m.id !== tempId));
        }
        setLastAttempt({ sid, text });
        setError(err instanceof Error ? err.message : 'Ошибка отправки сообщения');
        if (err instanceof TypeError) setBackendOnline(false);
      } finally {
        sendingRef.current = false;
        setSending(false);
      }
    },
    [loadSessions],
  );

  const send = useCallback(
    async (text: string) => {
      const value = text.trim();
      if (!value || sendingRef.current) return;

      let sid = activeIdRef.current;
      if (!sid) {
        try {
          const session = await api.createSession();
          setSessions((prev) => [{ ...session, message_count: 0 }, ...prev]);
          activeIdRef.current = session.id;
          setActiveId(session.id);
          sid = session.id;
        } catch (err) {
          setError(err instanceof Error ? err.message : 'Не удалось создать диалог');
          if (err instanceof TypeError) setBackendOnline(false);
          return;
        }
      }

      await performSend(sid, value);
    },
    [performSend],
  );

  const retry = useCallback(() => {
    if (!lastAttempt) return;
    performSend(lastAttempt.sid, lastAttempt.text);
  }, [lastAttempt, performSend]);

  const submitLead = useCallback(
    async (lead: { name: string; phone: string; company: string; session_id?: string }) => {
      await api.createLead(lead);
    },
    [],
  );

  const confirmDelete = useCallback(async () => {
    if (!confirmDeleteId) return;
    setDeleting(true);
    try {
      await api.deleteSession(confirmDeleteId);
      setSessions((prev) => prev.filter((s) => s.id !== confirmDeleteId));
      if (activeIdRef.current === confirmDeleteId) {
        activeIdRef.current = null;
        setActiveId(null);
        setMessages([]);
        setSuggestLead(false);
        setShowLeadModal(false);
        setLastAttempt(null);
        setError('');
      }
      setConfirmDeleteId(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось удалить диалог');
    } finally {
      setDeleting(false);
    }
  }, [confirmDeleteId]);

  const showWelcome = !messagesLoading && messages.length === 0 && !sending;
  const dialogTitle = sessions.find((s) => s.id === activeId)?.title ?? 'Новый диалог';

  return (
    <div className="flex h-screen flex-col bg-slate-50">
      <Header
        dialogTitle={dialogTitle}
        aiMode={aiMode}
        backendOnline={backendOnline}
        showDebug={showDebug}
        onToggleDebug={() => setShowDebug((v) => !v)}
        onOpenLead={() => setShowLeadModal(true)}
        onToggleSidebar={() => setSidebarMobileOpen((v) => !v)}
      />

      <div className="flex flex-1 overflow-hidden">
        <Sidebar
          sessions={sessions}
          activeId={activeId}
          loading={sessionsLoading}
          error={sessionsError}
          collapsed={sidebarCollapsed}
          mobileOpen={sidebarMobileOpen}
          onSelect={selectSession}
          onNew={newDialog}
          onDeleteRequest={setConfirmDeleteId}
          onToggleCollapse={() => setSidebarCollapsed((v) => !v)}
          onCloseMobile={() => setSidebarMobileOpen(false)}
        />

        <main className="flex flex-1 flex-col overflow-hidden">
          <div className="flex-1 overflow-y-auto px-4 py-6 sm:px-6">
            {messagesLoading ? (
              <div className="flex h-full items-center justify-center text-sm text-slate-400">
                Загрузка истории...
              </div>
            ) : showWelcome ? (
              <WelcomeScreen onSelect={send} disabled={sending} />
            ) : (
              <div className="mx-auto flex max-w-3xl flex-col gap-4">
                {messages.map((m) => (
                  <MessageBubble key={m.id} message={m} showDebug={showDebug} />
                ))}
                {sending && <TypingIndicator />}
                {error && (
                  <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                    <div>{error}</div>
                    {lastAttempt && (
                      <button
                        onClick={retry}
                        className="mt-2 rounded-md bg-red-600 px-3 py-1 text-xs font-medium text-white hover:bg-red-700"
                      >
                        Повторить
                      </button>
                    )}
                  </div>
                )}
                {suggestLead && !showLeadModal && (
                  <div className="rounded-xl border border-mts-red/20 bg-mts-light px-4 py-3">
                    <div className="text-sm font-medium text-slate-800">
                      Хотите обсудить проект со специалистом?
                    </div>
                    <button
                      onClick={() => setShowLeadModal(true)}
                      className="mt-2 rounded-lg bg-mts-red px-3 py-1.5 text-xs font-semibold text-white hover:bg-mts-dark"
                    >
                      Обсудить проект со специалистом
                    </button>
                  </div>
                )}
                <div ref={bottomRef} />
              </div>
            )}
          </div>

          <div className="shrink-0 border-t border-slate-200 bg-white px-4 pb-[calc(1rem+env(safe-area-inset-bottom))] pt-3 sm:px-6">
            <div className="mx-auto w-full max-w-3xl">
              <ChatInput onSend={send} disabled={sending} />
            </div>
          </div>
        </main>
      </div>

      {showLeadModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl">
            <LeadForm
              sessionId={activeId}
              onSubmit={submitLead}
              onClose={() => setShowLeadModal(false)}
            />
          </div>
        </div>
      )}

      {confirmDeleteId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-xl">
            <div className="text-base font-semibold text-slate-900">Удалить диалог?</div>
            <p className="mt-2 text-sm leading-relaxed text-slate-600">
              «{sessions.find((s) => s.id === confirmDeleteId)?.title ?? 'Диалог'}» и все его
              сообщения будут удалены безвозвратно. Заявки, если они есть, сохранятся.
            </p>
            <div className="mt-4 flex gap-2">
              <button
                onClick={confirmDelete}
                disabled={deleting}
                className="flex-1 rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50"
              >
                {deleting ? 'Удаление...' : 'Удалить'}
              </button>
              <button
                onClick={() => setConfirmDeleteId(null)}
                disabled={deleting}
                className="rounded-lg bg-slate-100 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-200 disabled:opacity-50"
              >
                Отмена
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
