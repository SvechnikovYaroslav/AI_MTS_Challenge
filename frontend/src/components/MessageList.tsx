import type { Message } from '../types';

interface Props {
  messages: Message[];
}

function DebugInfo({ m }: { m: Message }) {
  if (m.role !== 'assistant') return null;
  const parts: string[] = [];
  if (m.ai_status) parts.push(`ai: ${m.ai_status}`);
  if (m.latency_ms != null) parts.push(`${m.latency_ms} ms`);
  const sources = (m.sources ?? []).map((s) => s.file).join(', ');
  if (sources) parts.push(`источники: ${sources}`);
  if (parts.length === 0) return null;
  return <div className="mt-1 text-[11px] text-slate-400">{parts.join(' · ')}</div>;
}

export function MessageList({ messages }: Props) {
  if (messages.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-slate-400">
        Опишите вашу проблему с энергопотреблением — консультант ответит на основе базы знаний МТС.
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      {messages.map((m) => (
        <div key={m.id} className={m.role === 'user' ? 'self-end' : 'self-start'}>
          <div
            className={
              m.role === 'user'
                ? 'max-w-[75%] rounded-2xl rounded-br-sm bg-blue-600 px-4 py-2 text-white'
                : 'max-w-[85%] rounded-2xl rounded-bl-sm border border-slate-200 bg-white px-4 py-2 text-slate-800 shadow-sm'
            }
          >
            <div className="whitespace-pre-wrap text-sm">{m.content}</div>
            <DebugInfo m={m} />
          </div>
        </div>
      ))}
    </div>
  );
}
