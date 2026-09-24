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

/** An artifact made during a turn, or loaded back with a conversation. */
export interface Artifact {
  id: string
  /** The answer that made it, so a reload puts the card back in the right
   *  place. Null when the message it belonged to was deleted. */
  message_id?: string | null
  kind: string
  title: string
  version: number
  width: number
  height: number
  created_at: string
}

export interface ArtifactDetail extends Artifact {
  html: string
  /** What the frame may do. Empty is the strongest setting there is. */
  sandbox: string
  versions: { version: number; size_bytes: number; created_at: string }[]
}

/** A build in progress. Held separately from the finished artifact because it
 *  has no id yet and may never get one. */
/** One finished piece of something built in parts — a slide of a deck. */
export interface ArtifactPart {
  index: number
  total: number
  title: string
  html: string
}

export interface ArtifactBuild {
  kind: string
  title: string
  steps: { label: string; detail: string }[]
  /** The document as it is written. Shown as source; the preview waits. */
  source: string
  /** Pieces finished so far, in order. A deck shows slide one while slide
   *  seven is still being written. */
  parts: ArtifactPart[]
  /** What is coming, named before it exists, so the shape is on screen from
   *  the start. */
  plan?: string[]
  /** The look it has chosen, so it can be shown in its own colours while it is
   *  still being built. */
  design?: {
    movement: string
    palette: string[]
    display_font: string
    body_font: string
    /** One sentence on what is being made. For a game, the loop: what the
     *  player will actually be doing. */
    rationale?: string
  }
  /** The shape it will be, so the forming card is the artifact's proportions
   *  rather than a rectangle picked by the panel. */
  width?: number
  height?: number
  failed?: string | null
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
  /** What this answer made, if anything. */
  artifacts?: Artifact[]
  /** The build, while it is happening. */
  building?: ArtifactBuild | null
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
  /** What the panel is showing. It is what "make it warmer" refers to. */
  artifact_id?: string | null
  /** The person's IANA zone, so "today" on the server is their today. */
  timezone?: string
}
