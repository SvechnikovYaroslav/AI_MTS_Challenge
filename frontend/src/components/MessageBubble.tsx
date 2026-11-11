import { useState, type ReactNode } from 'react';
import type { Message, Source } from '../types';

function isSafeUrl(url: string): boolean {
  try {
    const u = new URL(url);
    return u.protocol === 'http:' || u.protocol === 'https:';
  } catch {
    return false;
  }
}

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const regex = /(\[([^\]]+)\]\(([^)\s]+)\))|(https?:\/\/[^\s]+)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let i = 0;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }
    const [full, , mdLabel, mdUrl, bareUrl] = match;
    const label = mdLabel ?? bareUrl ?? full;
    const url = mdUrl ?? bareUrl ?? '';
    if (isSafeUrl(url)) {
      nodes.push(
        <a
          key={`${keyPrefix}-${i++}`}
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-mts-red underline underline-offset-2 hover:text-mts-dark"
        >
          {label}
        </a>,
      );
    } else {
      nodes.push(full);
    }
    lastIndex = match.index + full.length;
  }

  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }
  return nodes;
}

function renderContent(content: string): ReactNode {
  const lines = content.split('\n');
  const blocks: ReactNode[] = [];
  let listItems: string[] = [];
  let key = 0;

  const flushList = () => {
    if (listItems.length > 0) {
      blocks.push(
        <ul key={key++} className="my-2 list-disc space-y-1 pl-5">
          {listItems.map((item, idx) => (
            <li key={idx}>{renderInline(item, `li-${key}-${idx}`)}</li>
          ))}
        </ul>,
      );
      listItems = [];
    }
  };

  for (const line of lines) {
    const trimmed = line.trim();
    const bullet = trimmed.match(/^[-*•]\s+(.*)$/);
    if (bullet) {
      listItems.push(bullet[1]);
      continue;
    }
    flushList();
    if (trimmed === '') {
      blocks.push(<div key={key++} className="h-2" />);
    } else {
      blocks.push(
        <p key={key++} className="my-1 first:mt-0 last:mb-0">
          {renderInline(trimmed, `p-${key}`)}
        </p>,
      );
    }
  }
  flushList();

  return <div className="text-sm leading-relaxed">{blocks}</div>;
}

function DebugDetails({ m }: { m: Message }) {
  if (m.role !== 'assistant') return null;
  const sources = (m.sources ?? []) as Source[];
  return (
    <div className="mt-3 border-t border-slate-100 pt-2 text-[11px] text-slate-500">
      <div className="flex flex-wrap gap-x-3 gap-y-1">
        {m.ai_status && <span>ai_status: {m.ai_status}</span>}
        {m.latency_ms != null && <span>latency: {m.latency_ms} ms</span>}
      </div>
      {sources.length > 0 && (
        <div className="mt-1">
          <span className="font-medium">Источники:</span>{' '}
          {sources.map((s, idx) => (
            <span key={idx} className="mr-2 inline-flex items-center gap-1">
              <span className="rounded bg-slate-100 px-1.5 py-0.5">{s.file}</span>
              {s.mock && <span className="rounded bg-amber-100 px-1.5 py-0.5 text-amber-700">mock</span>}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

interface Props {
  message: Message;
  showDebug: boolean;
}

export function MessageBubble({ message, showDebug }: Props) {
  const [copied, setCopied] = useState(false);
  const isUser = message.role === 'user';

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard недоступен */
    }
  };

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`group max-w-[85%] rounded-2xl px-4 py-3 shadow-sm sm:max-w-[75%] ${
          isUser
            ? 'rounded-br-sm bg-mts-red text-white'
            : 'rounded-bl-sm border border-slate-200 bg-white text-slate-800'
        }`}
      >
        {renderContent(message.content)}
        {showDebug && <DebugDetails m={message} />}
        {!isUser && (
          <button
            onClick={copy}
            className="mt-2 flex items-center gap-1 text-[11px] text-slate-400 opacity-100 transition-opacity hover:text-slate-600 md:opacity-0 md:group-hover:opacity-100"
          >
            <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
            </svg>
            {copied ? 'Скопировано' : 'Копировать'}
          </button>
        )}
      </div>
    </div>
  );
}
