import { useState, type FormEvent } from 'react';

interface Props {
  sessionId: string | null;
  onSubmit: (lead: { name: string; phone: string; company: string; session_id?: string }) => Promise<void>;
  onClose: () => void;
}

export function LeadForm({ sessionId, onSubmit, onClose }: Props) {
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [company, setCompany] = useState('');
  const [status, setStatus] = useState<'idle' | 'sending' | 'done' | 'error'>('idle');
  const [error, setError] = useState('');

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setStatus('sending');
    setError('');
    try {
      await onSubmit({
        name: name.trim(),
        phone: phone.trim(),
        company: company.trim(),
        session_id: sessionId ?? undefined,
      });
      setStatus('done');
    } catch (err) {
      setStatus('error');
      setError(err instanceof Error ? err.message : 'Ошибка отправки');
    }
  };

  if (status === 'done') {
    return (
      <div className="rounded-lg border border-green-200 bg-green-50 p-4 text-sm text-green-800">
        Заявка отправлена! Менеджер свяжется с вами.
        <button onClick={onClose} className="mt-2 block text-green-700 underline">
          Закрыть
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-2 rounded-lg border border-slate-200 bg-white p-4">
      <div className="text-sm font-semibold text-slate-800">Заявка менеджеру</div>
      <input
        required
        minLength={2}
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="ФИО"
        className="rounded border border-slate-300 px-3 py-1.5 text-sm outline-none focus:border-blue-500"
      />
      <input
        required
        minLength={5}
        value={phone}
        onChange={(e) => setPhone(e.target.value)}
        placeholder="Телефон"
        className="rounded border border-slate-300 px-3 py-1.5 text-sm outline-none focus:border-blue-500"
      />
      <input
        value={company}
        onChange={(e) => setCompany(e.target.value)}
        placeholder="Компания"
        className="rounded border border-slate-300 px-3 py-1.5 text-sm outline-none focus:border-blue-500"
      />
      {status === 'error' && <div className="text-xs text-red-600">{error}</div>}
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={status === 'sending'}
          className="rounded bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {status === 'sending' ? 'Отправка...' : 'Отправить заявку'}
        </button>
        <button type="button" onClick={onClose} className="rounded px-3 py-1.5 text-sm text-slate-500 hover:bg-slate-100">
          Отмена
        </button>
      </div>
    </form>
  );
}
