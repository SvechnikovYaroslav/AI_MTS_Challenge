import type { Session } from '../types';

interface Props {
  sessions: Session[];
  activeId: string | null;
  loading: boolean;
  error: string;
  collapsed: boolean;
  mobileOpen: boolean;
  onSelect: (id: string) => void;
  onNew: () => void;
  onToggleCollapse: () => void;
  onCloseMobile: () => void;
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
  } catch {
    return iso;
  }
}

export function Sidebar({
  sessions,
  activeId,
  loading,
  error,
  collapsed,
  mobileOpen,
  onSelect,
  onNew,
  onToggleCollapse,
  onCloseMobile,
}: Props) {
  const content = (
    <div className="flex h-full flex-col bg-white">
      <div className="flex items-center justify-between border-b border-slate-200 p-4">
        <div>
          <div className="text-base font-bold text-slate-900">МТС EnergyTool</div>
          <div className="text-xs text-slate-500">AI Consultant</div>
        </div>
        <button
          onClick={onToggleCollapse}
          className="hidden rounded-md p-1.5 text-slate-500 hover:bg-slate-100 md:block"
          aria-label={collapsed ? 'Развернуть панель' : 'Свернуть панель'}
        >
          <svg className={`h-4 w-4 transition-transform ${collapsed ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
        </button>
      </div>

      <div className="p-3">
        <button
          onClick={onNew}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-mts-red px-3 py-2 text-sm font-semibold text-white hover:bg-mts-dark"
        >
          <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          Новый диалог
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-2 pb-3">
        <div className="px-2 pb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
          История диалогов
        </div>
        {loading && <div className="px-2 py-4 text-xs text-slate-400">Загрузка...</div>}
        {error && <div className="px-2 py-4 text-xs text-red-600">{error}</div>}
        {!loading && !error && sessions.length === 0 && (
          <div className="px-2 py-4 text-xs text-slate-400">Пока нет диалогов</div>
        )}
        <div className="flex flex-col gap-1">
          {sessions.map((s) => (
            <button
              key={s.id}
              onClick={() => {
                onSelect(s.id);
                onCloseMobile();
              }}
              className={`rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                s.id === activeId
                  ? 'bg-mts-light text-mts-red'
                  : 'text-slate-700 hover:bg-slate-100'
              }`}
            >
              <div className="truncate font-medium">{s.title}</div>
              <div className="mt-0.5 flex items-center justify-between text-[11px] text-slate-400">
                <span>{formatDate(s.created_at)}</span>
                {typeof s.message_count === 'number' && <span>{s.message_count} сообщ.</span>}
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop sidebar */}
      <aside
        className={`hidden shrink-0 border-r border-slate-200 transition-all duration-200 md:block ${
          collapsed ? 'w-14' : 'w-72'
        }`}
      >
        {collapsed ? (
          <div className="flex h-full flex-col items-center gap-3 py-4">
            <div className="text-xs font-bold text-mts-red [writing-mode:vertical-rl]">МТС</div>
            <button
              onClick={onToggleCollapse}
              className="rounded-md p-2 text-slate-500 hover:bg-slate-100"
              aria-label="Развернуть панель"
            >
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
            </button>
            <button
              onClick={onNew}
              className="rounded-lg bg-mts-red p-2 text-white hover:bg-mts-dark"
              aria-label="Новый диалог"
            >
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
            </button>
          </div>
        ) : (
          content
        )}
      </aside>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={onCloseMobile} />
          <aside className="absolute left-0 top-0 h-full w-72 shadow-xl">{content}</aside>
        </div>
      )}
    </>
  );
}
