import type { AdTip, ChatContext, ChatResponse, CompanyList, LinkDetails, Page, ProfileStatus, RiskInfo, WidgetDetails } from "./types";

export class ApiError extends Error {
  constructor(public status: number, msg: string) { super(msg); }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch("/api" + path, init);
  if (!r.ok) throw new ApiError(r.status, `${r.status} ${path}`);
  return r.json();
}

export const api = {
  page: (profile?: string | null) => call<Page>(profile ? `/page?profile=${encodeURIComponent(profile)}` : "/page"),
  companies: (q: string, offset: number, limit = 50) => call<CompanyList>(`/companies?q=${encodeURIComponent(q)}&offset=${offset}&limit=${limit}`),
  setProfile: (body: { company: string; role: string }) =>
    call<ProfileStatus>("/profile", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  adTip: (body: { company: string; role: string }) =>
    call<AdTip>("/ad-tip", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  profileStatus: (key: string) => call<ProfileStatus>(`/profile/${key}`),
  widget: (id: string) => call<WidgetDetails>(`/widgets/${id}`),
  risks: (id: string) => call<RiskInfo>(`/widgets/${id}/risks`),
  link: (id: string) => call<LinkDetails>(`/links/${id}`),
  chat: (body: { context: ChatContext; session_id: string | null; message: string | null; page_version: number }) =>
    call<ChatResponse>("/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
};
