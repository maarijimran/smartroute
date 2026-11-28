export type Role = "superadmin" | "admin" | "user";
export type PrivacyMode = "local_only" | "cloud_allowed";

export interface User {
  id: string;
  email: string;
  name: string;
  role: Role;
  is_active: boolean;
  allow_confidential_cloud: boolean | null;
  monthly_budget_usd: number | null;
  created_at: string;
}

export interface Permissions {
  role: Role;
  cloud_enabled: boolean;
  may_send_confidential_to_cloud: boolean;
  consent_required: boolean;
  may_pin_model: boolean;
  monthly_budget_usd: number | null;
  ocr_enabled: boolean;
}

export interface Vendor {
  id: string;
  label: string;
  adapter: string;
  needs_key: boolean;
  needs_base_url: boolean;
  default_base_url: string | null;
}

export interface Model {
  id: string;
  name: string;
  display_name: string;
  vendor: string;
  model_id: string;
  tier: "local" | "cheap" | "strong";
  is_local: boolean;
  base_url: string | null;
  context_window: number;
  max_output_tokens: number;
  price_in_per_mtok: number;
  price_out_per_mtok: number;
  price_updated_at: string;
  params: Record<string, unknown>;
  enabled: boolean;
  latency_ewma_ms: number;
  unhealthy_until: string | null;
  last_error: string | null;
}

export interface Credential {
  id: string;
  user_id: string | null;
  vendor: string;
  label: string;
  base_url: string | null;
  api_version: string | null;
  key_hint: string;
  created_at: string;
}

export type Tier = "local" | "cheap" | "strong";

export interface TierSlot {
  tier: Tier;
  configured: boolean;
  model: Model | null;
  key_vendor: string | null;
  key_hint: string | null;
  api_version: string | null;
  card: ModelCardInfo | null;
  calibrating: boolean;
}

/* Router v2: what is known about a tier model's ability. */
export interface ModelCardInfo {
  status: "trained" | "calibrated" | "calibrating" | "learning" | "uncalibrated" | "no_router";
  n?: number;
  level?: number;
  abilities?: number[];
  level_sd?: number;
  router_version?: string;
  calibration?: {
    asked?: number;
    scored?: number;
    failed?: number;
    cost_usd?: number;
    uncertainty?: number | null;
    target_uncertainty?: number;
    max_items?: number;
    error?: string | null;
    note?: string;
    finished_at?: string;
  };
}

export interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  default_privacy_mode: PrivacyMode;
  revoked: boolean;
  created_at: string;
  last_used_at: string | null;
  key?: string;
}

export interface Doc {
  id: string;
  filename: string;
  label: "public" | "confidential";
  pages: number;
  n_chunks: number;
  ocr_pages: number;
  created_at: string;
}

export interface Session {
  id: string;
  title: string;
  privacy_mode: PrivacyMode;
  document_ids: string[];
  confidential: boolean;
  persist: boolean;
  created_at: string;
  last_active_at: string;
}

export interface Source {
  n: number;
  document: string;
  page: number;
}

/** Routing metadata returned with every answer (Outcome.public() on the server). */
export interface RouteMeta {
  event_id: string;
  status: string;
  model: string | null;
  served_model: string | null;
  tier: string | null;
  is_local: boolean | null;
  policy: string;
  policy_version: number;
  explanation: string;
  propensity: number | null;
  explored: boolean;
  in_tokens: number;
  out_tokens: number;
  cost_usd: number;
  latency_ms: number;
  ttft_ms: number | null;
  routing_overhead_ms: number;
  attempts: number;
  fallback_from: string | null;
  notices: string[];
  sources: Source[];
  sensitive: boolean;
  entity_types: string[];
  eligible: string[];
  exclusions: Record<string, string>;
  abstain_kind: string | null;
  error: string | null;
  cache_hit: boolean;
  context_compressed: boolean;
  follow_up: boolean;
  history_mode: "none" | "full" | "summary" | "relevant_turns";
  history_messages: number;
  history_sent: number;
  cache_read_tokens: number;
  scores: Record<string, ScoreParts>;
}

/* How one eligible model scored for a learned routing policy. */
export interface ScoreParts {
  tier: string;
  total: number;
  quality?: number;
  cost?: number;
  speed?: number;
  bonus?: number;
  pacer?: number;
  predicted_quality?: number;
  predicted_reward?: number;
  quality_sd?: number;
  card?: string;
  below_floor?: boolean;
  est_cost_usd: number;
  latency_s: number;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  event_id: string | null;
  meta: Partial<RouteMeta>;
  created_at: string;
}

export type ChatEvent =
  | { type: "route"; event_id: string; model: string | null; policy: string; explanation: string; sensitive: boolean; entity_types: string[] }
  | { type: "delta"; text: string }
  | { type: "done"; text: string; meta: RouteMeta };

export interface Policy {
  cloud_enabled: boolean;
  allow_confidential_cloud_default: boolean;
  require_consent_for_confidential: boolean;
  blocking_entity_types: string[];
  exempt_person_in_public_documents: boolean;
  audit_preview_chars: number;
  allow_self_registration: boolean;
  users_may_pin_model: boolean;
  routing_policy: "rules" | "frozen" | "bandit" | "linucb" | "calibrated" | "calibrated_ucb";
  quality_floor: number;
  v2_ucb_alpha: number;
  reward_mode: "split" | "full";
  weights: { quality: number; cost: number; latency: number };
  c_ref_usd: number;
  l_ref_s: number;
  eps_start: number;
  eps_end: number;
  eps_decay_steps: number;
  update_batch_size: number;
  ridge_lambda: number;
  linucb_alpha: number;
  linucb_gamma: number;
  max_retries: number;
  output_caps: Record<string, number>;
  context_safety_margin: number;
  retrieval_top_k: number;
  history_budget_tokens: number;
  history_summary_enabled: boolean;
  cache_enabled: boolean;
  cache_ttl_s: number;
  global_monthly_budget_usd: number | null;
  session_expiry_minutes: number;
  metadata_retention_days: number;
  audit_retention_days: number;
}

export interface PolicyChange {
  id: string;
  created_at: string;
  actor: string;
  target: string;
  changes: Record<string, [unknown, unknown]>;
}

export interface LearnerVersion {
  name: string;
  version: number;
  active: boolean;
  note: string;
  created_at: string;
  n_scored: number;
  feature_dim: number | null;
  arms: Record<string, number>;
}

export interface AuditRow {
  id: string;
  created_at: string;
  user_email: string;
  source: string;
  privacy_mode: string;
  triggers: string[];
  entity_types: string[];
  decision: string;
  decision_reason: string;
  consent_given: boolean;
  destination_model: string | null;
  left_trusted_boundary: boolean;
  payload_sha256: string;
  masked_preview: string;
  routing_event_id: string | null;
}

export interface Summary {
  days: number;
  scope: string;
  measured: {
    requests: number;
    answered: number;
    by_status: Record<string, number>;
    cost_usd: number;
    latency_p50_ms: number | null;
    latency_p95_ms: number | null;
    routing_overhead_p50_ms: number | null;
    local_share: number | null;
    cache_hits: number;
  };
  estimated: {
    reference_model: string | null;
    strong_only_cost_usd: number | null;
    saving_vs_strong_only: number | null;
    note: string;
  };
  privacy: { confidential_requests: number; cloud_blocked: number; sent_to_cloud_with_consent: number };
  by_model: { model: string; tier: string | null; requests: number; cost_usd: number; avg_latency_ms: number; avg_quality: number | null; rated: number }[];
  daily: { date: string; requests: number; cost_usd: number; est_strong_only_usd: number }[];
}

export interface EventRow {
  id: string;
  created_at: string;
  source: string;
  task: string;
  privacy_mode: string;
  sensitive: boolean;
  status: string;
  model: string | null;
  policy: string;
  explanation: string;
  exclusions: Record<string, string>;
  in_tokens: number;
  out_tokens: number;
  cost_usd: number;
  latency_ms: number;
  quality: number | null;
  reward: number | null;
}
