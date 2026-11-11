import { useState, type FormEvent } from 'react';

interface Props {
  sessionId: string | null;
  onSubmit: (lead: { name: string; phone: string; company: string; session_id?: string }) => Promise<void>;
  onClose: () => void;
}

const inputClass =
  'w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition-colors focus:border-mts-red';

// Российский формат: +7 (XXX) XXX-XX-XX.
// Пользователь может вводить номер без кода страны: 953... -> +7 (953) ...
function formatRuPhone(input: string): string {
  let d = input.replace(/\D/g, '');
  if (d.startsWith('8') && d.length === 11) d = '7' + d.slice(1);
  if (d.startsWith('7')) d = d.slice(1);
  d = d.slice(0, 10);
  if (!d) return '';

  const parts = [d.slice(0, 3), d.slice(3, 6), d.slice(6, 8), d.slice(8, 10)];
  let out = '+7';
  if (parts[0]) out += ` (${parts[0]}`;
  if (d.length >= 3) out += ')';
  if (parts[1]) out += ` ${parts[1]}`;
  if (parts[2]) out += `-${parts[2]}`;
  if (parts[3]) out += `-${parts[3]}`;
  return out;
}

function phoneDigits(phone: string): string {
  return phone.replace(/\D/g, '');
}

export function LeadForm({ sessionId, onSubmit, onClose }: Props) {
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [company, setCompany] = useState('');
  const [status, setStatus] = useState<'idle' | 'sending' | 'done' | 'error'>('idle');
  const [error, setError] = useState('');

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (phoneDigits(phone).length !== 11) {
      setStatus('error');
      setError('Введите номер полностью: +7 и 10 цифр');
      return;
    }
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
      <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-5 text-sm text-emerald-800">
        <div className="font-semibold">Заявка отправлена</div>
        <p className="mt-1">Менеджер свяжется с вами для обсуждения проекта.</p>
        <button onClick={onClose} className="mt-3 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700">
          Закрыть
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      <div>
        <div className="text-base font-semibold text-slate-900">Обсудить проект со специалистом</div>
        <p className="mt-1 text-xs text-slate-500">
          Оставьте контакты — менеджер МТС EnergyTool свяжется с вами.
        </p>
      </div>

      <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
        ФИО
        <input
          required
          minLength={2}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Иван Иванов"
          className={inputClass}
        />
      </label>

      <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
        Телефон
        <input
          required
          value={phone}
          onChange={(e) => setPhone(formatRuPhone(e.target.value))}
          placeholder="+7 (900) 000-00-00"
          inputMode="tel"
          autoComplete="tel"
          className={inputClass}
        />
      </label>

      <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
        Компания
        <input
          value={company}
          onChange={(e) => setCompany(e.target.value)}
          placeholder="ООО «Компания»"
          className={inputClass}
        />
      </label>

      {status === 'error' && (
        <div className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}. Попробуйте ещё раз.
        </div>
      )}

      <div className="flex gap-2 pt-1">
        <button
          type="submit"
          disabled={status === 'sending'}
          className="flex-1 rounded-lg bg-mts-red px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-mts-dark disabled:opacity-50"
        >
          {status === 'sending' ? 'Отправка...' : 'Отправить заявку'}
        </button>
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg bg-slate-100 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-200"
        >
          Отмена
        </button>
      </div>
    </form>
  );
}
