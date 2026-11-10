import { useState, type FormEvent } from 'react';

interface Props {
  onSend: (text: string) => void;
  disabled?: boolean;
}

export function ChatInput({ onSend, disabled }: Props) {
  const [text, setText] = useState('');

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const value = text.trim();
    if (!value || disabled) return;
    onSend(value);
    setText('');
  };

  return (
    <form onSubmit={submit} className="flex gap-2 border-t border-slate-200 p-3">
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Опишите проблему с энергопотреблением..."
        maxLength={4000}
        disabled={disabled}
        className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500 disabled:bg-slate-100"
      />
      <button
        type="submit"
        disabled={disabled || !text.trim()}
        className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
      >
        Отправить
      </button>
    </form>
  );
}
