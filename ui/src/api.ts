import type { ChatContext, ChatResponse, LinkDetails, Page, RiskInfo, WidgetDetails } from "./types";

export class ApiError extends Error {
  constructor(public status: number, msg: string) { super(msg); }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch("/api" + path, init);
  if (!r.ok) throw new ApiError(r.status, `${r.status} ${path}`);
  return r.json();
}

export const api = {
  page: () => call<Page>("/page"),
  widget: (id: string) => call<WidgetDetails>(`/widgets/${id}`),
  risks: (id: string) => call<RiskInfo>(`/widgets/${id}/risks`),
  link: (id: string) => call<LinkDetails>(`/links/${id}`),
  chat: (body: { context: ChatContext; session_id: string | null; message: string | null; page_version: number }) =>
    call<ChatResponse>("/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
};
