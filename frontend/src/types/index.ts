// Типы соответствуют docs/api-contract.md

export interface Source {
  file: string;
  mock?: boolean;
  score?: number;
  [key: string]: unknown;
}

export interface Session {
  id: string;
  title: string;
  created_at: string;
  message_count?: number;
}

export interface Message {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  sources?: Source[] | null;
  latency_ms?: number | null;
  ai_status?: string | null;
  created_at: string;
}

export interface ChatResponse {
  session_id: string;
  answer: string;
  sources: Source[];
  latency_ms: number;
  suggest_lead: boolean;
  ai_status: string;
}

export interface Lead {
  id: number;
  name: string;
  phone: string;
  company: string;
  session_id: string | null;
  created_at: string;
}
