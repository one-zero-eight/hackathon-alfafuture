// Contract types, see docs/backend.md
export type Column = "news" | "analytics" | "decisions";

export type Confidence = "reliable" | "probable" | "possible";
export type Source = "ai" | "alfa" | "human";
export type Urgency = "urgent" | "medium_term" | "not_urgent";
export interface Tags { confidence?: Confidence; source?: Source; industry?: string; urgency?: Urgency }
export interface WidgetSkeleton { id: string; column: Column; title: string; url?: string; tags?: Tags }
export interface LinkSkeleton { id: string; from: string; to: string }
export interface Company { name: string; okved: string; role: string; date: string }
export type Stage = "search" | "rank" | "analysis";
export interface ProfileStatus {
  key: string; status: "queued" | "running" | "ready" | "failed"; error: string;
  cached?: boolean; // POST /profile only: the page was already in the database
  stage?: Stage; found?: number | null; selected?: number | null; // GET /profile/{key} only: progress of a running profile
}
export interface CompanyItem { id: string; okved_name: string }
export interface CompanyList { total: number; items: CompanyItem[] }
export interface Page { version: number; company: Company; widgets: WidgetSkeleton[]; links: LinkSkeleton[] }

export interface Series { name: string; color: string; values: number[] }
export interface ChartData { type: "line" | "bars"; unit: string; demo?: boolean; labels: string[]; series: Series[] }
export interface WidgetDetails {
  id: string; text: string; src?: string; date?: string;
  kpis?: { value: string; label: string }[]; chart?: ChartData;
}
export interface Risk { name: string; probability: number; impact: number; mitigation: string }
export interface RiskInfo { id: string; steps: string[]; bank_offer: string | null; risks: Risk[] }
export interface LinkDetails { id: string; from: string; to: string; text: string }

export type Op =
  | { op: "add_widget"; widget: WidgetSkeleton }
  | { op: "update_widget"; id: string; fields?: Partial<Omit<WidgetSkeleton, "id">> }
  | { op: "remove_widget"; id: string }
  | { op: "add_link"; link: LinkSkeleton }
  | { op: "update_link"; id: string; fields?: Partial<Omit<LinkSkeleton, "id">> }
  | { op: "remove_link"; id: string };
export interface Patch { base_version: number; version: number; ops: Op[] }

// Scenario recognised by the server (docs/backend.md); the UI infers one from the patch when the field is absent
export type ScenarioKind = "question" | "extend" | "perspective" | "edit" | "remove" | "link" | "proposal";
export interface Scenario { kind: ScenarioKind; reason?: string }

export type ChatContext = { type: "widget" | "link"; id: string };
export interface ChatReply { text: string; basis: string[]; followups: string[] }
export interface ChatResponse { session_id: string; reply: ChatReply; patch: Patch | null; scenario?: Scenario }
