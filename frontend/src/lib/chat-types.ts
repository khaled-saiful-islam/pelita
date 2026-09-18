/**
 * The shapes a conversation is made of.
 *
 * Their own module so components can import a type without pulling in the hook
 * that drives the stream — and so the hook is about behaviour rather than being
 * a third declarations, a third transport and a third orchestration.
 */

export type Role = 'user' | 'assistant'
export type Rating = 'up' | 'down'
export type SearchMode = 'auto' | 'always' | 'off'

export interface Source {
  rank: number
  title: string
  url: string
  snippet: string
  /** Set only on image-search results. */
  thumbnail_url?: string | null
  image_url?: string | null
}

export interface ImageResult {
  rank: number
  title: string
  /** The page the image appears on, not the image file. */
  url: string
  source: string
  thumbnail_url: string
  image_url: string
}

export interface GuardAlert {
  source: string
  severity: 'low' | 'medium' | 'high'
  rules: string[]
  evidence: string
}

export interface ToolActivity {
  tool: string
  status: 'running' | 'done' | 'failed'
  label: string
  detail: string
}

export interface Totals {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cost: string | number
  currency: string
  /** True when any message was priced from an estimate. */
  estimated: boolean
}

/** A file attached to a conversation. Mirrors DocumentResponse. */
export interface AttachedFile {
  id: string
  /** Null while the file is still in the composer. */
  message_id: string | null
  filename: string
  media_type: string
  size_bytes: number
  /** "page" for a PDF, "paragraph" for a docx, "line" for text. */
  unit: string
  unit_count: number
  token_count: number
  /** A data URI, images only — what the card shows instead of a file icon. */
  thumbnail?: string | null
  created_at: string
}

export interface ChatMessage {
  id: string
  role: Role
  content: string
  finish_reason: string | null
  model: string | null
  created_at: string
  prompt_tokens: number
  completion_tokens: number
  cost: string | number
  /** 'provider' when the model reported the counts, 'estimated' when we did. */
  usage_source: string | null
  sources?: Source[]
  images?: ImageResult[]
  /** What tools ran for this answer, in order. */
  tools?: ToolActivity[]
  /** Guard findings for this turn. */
  guards?: GuardAlert[]
  /** Files sent with this message, shown as cards above it. */
  documents?: AttachedFile[]
  /** True only for the message currently being written. */
  streaming?: boolean
  error?: string | null
}

export interface FeedbackRecord {
  message_id: string
  rating: Rating
  reason: string | null
}

export interface ConversationDetail {
  id: string
  title: string
  created_at: string
  updated_at: string
  messages: ChatMessage[]
  feedback: Record<string, FeedbackRecord>
  language: string | null
  totals: Totals
}

// --- wire payloads ------------------------------------------------------

export interface StartPayload {
  conversation_id: string
  user_message_id: string
  assistant_message_id: string
  title: string
  language: string | null
}

export interface UsagePayload {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cost: number
  currency: string
  source: string
}

export interface StreamBody {
  conversation_id?: string | null
  content?: string
  regenerate_of?: string
  search_mode?: SearchMode
}
