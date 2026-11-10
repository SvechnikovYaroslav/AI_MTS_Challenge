import type { Session } from '../types';

interface Props {
  sessions: Session[];
  activeId: string | null;
  onSelect: (id: string) => void;
}

export function SessionList({ sessions, activeId, onSelect }: Props) {
  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-slate-200 p-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
        Диалоги
      </div>
      <div className="flex-1 overflow-y-auto">
        {sessions.length === 0 && (
          <div className="p-3 text-xs text-slate-400">Пока нет диалогов</div>
        )}
        {sessions.map((s) => (
          <button
            key={s.id}
            onClick={() => onSelect(s.id)}
            className={
              'block w-full truncate px-3 py-2 text-left text-sm hover:bg-slate-100 ' +
              (s.id === activeId ? 'bg-blue-50 text-blue-700' : 'text-slate-700')
            }
          >
            {s.title}
            {typeof s.message_count === 'number' && (
              <span className="ml-1 text-xs text-slate-400">({s.message_count})</span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}
