interface Props {
  dialogTitle: string;
  aiMode: string;
  backendOnline: boolean;
  showDebug: boolean;
  onToggleDebug: () => void;
  onOpenLead: () => void;
  onToggleSidebar: () => void;
}

export function Header({
  dialogTitle,
  aiMode,
  backendOnline,
  showDebug,
  onToggleDebug,
  onOpenLead,
  onToggleSidebar,
}: Props) {
  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-slate-200 bg-white px-3 sm:px-4">
      <div className="flex min-w-0 items-center gap-2">
        <button
          onClick={onToggleSidebar}
          className="rounded-md p-2 text-slate-600 hover:bg-slate-100 md:hidden"
          aria-label="Открыть меню"
        >
          <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-slate-900">{dialogTitle}</div>
          <div className="truncate text-xs text-slate-500">Диалог с консультантом</div>
        </div>
      </div>

      <div className="flex items-center gap-2">
        {showDebug && (
          <>
            <span
              className={`hidden rounded-full px-2 py-0.5 text-[11px] font-medium sm:inline ${
                backendOnline ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'
              }`}
            >
              Бэкенд: {backendOnline ? 'онлайн' : 'офлайн'}
            </span>
            {aiMode && (
              <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700">
                AI: {aiMode}
              </span>
            )}
          </>
        )}
        <button
          onClick={onToggleDebug}
          className={`rounded-md px-2.5 py-1 text-xs font-medium ${
            showDebug ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
          }`}
        >
          Тех. детали
        </button>
        <button
          onClick={onOpenLead}
          className="rounded-md bg-mts-red px-3 py-1.5 text-xs font-semibold text-white hover:bg-mts-dark sm:text-sm"
        >
          Обсудить проект
        </button>
      </div>
    </header>
  );
}
