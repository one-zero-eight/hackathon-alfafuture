// The single entry point to the AI, mounted once in App so it shows on every screen
export function AskAiButton({ onClick }: { onClick: () => void }) {
  return <button className="ask-ai" onClick={onClick} aria-label="Спросить ИИ">✦ Спросить ИИ</button>;
}
