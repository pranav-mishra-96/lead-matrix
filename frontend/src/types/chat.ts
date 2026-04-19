// Mirror of backend Pydantic models in app/schemas/events.py.
// Keep these in lockstep with the backend — when you change an event
// shape on the server, update the type here.

export type Role = "user" | "assistant" | "system";

export interface ChatMessage {
  id: string;                       // client-generated UUID
  role: Role;
  content: string;
  streaming?: boolean;              // true while tokens are arriving
}

// ---------------------------------------------------------------------------
// Server-sent event payloads
// ---------------------------------------------------------------------------
export interface TokenEvent {
  type: "token";
  content: string;
}

export interface ProfileEvent {
  type: "profile";
  business_segment: string | null;
  annual_usage_mwh: number | null;
  contract_status: string | null;
  building_age_years: number | null;
  square_footage: number | null;
  usage_was_estimated: boolean;
}

export interface TierEvent {
  type: "tier";
  tier: string;
  matched_rule: string;
}

export interface DoneEvent {
  type: "done";
}

export interface ErrorEvent {
  type: "error";
  message: string;
}

export type AgentEvent =
  | TokenEvent
  | ProfileEvent
  | TierEvent
  | DoneEvent
  | ErrorEvent;

// ---------------------------------------------------------------------------
// API response shapes
// ---------------------------------------------------------------------------
export interface StartConversationResponse {
  conversation_id: string;
  assistant_message: string;
}