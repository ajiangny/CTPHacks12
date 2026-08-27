import { useEffect, useRef, useState } from 'react';
import { motion } from 'motion/react';
import type { Term } from './types';

type Msg = { role: 'user' | 'model'; text: string };
const T = { base: { duration: 0.2, ease: [0.2, 0, 0, 1] as const } };
const ring = 'outline-none focus-visible:ring-2 focus-visible:ring-accent/40';

/** Advisor chatbot (Gemini via /api/chat). Knows the approved plan, progress and what is eligible next term. */
export function Chat({ program, terms, term, onClose }: { program: string; terms: Term[]; term: Term['kind']; onClose: () => void }) {
  const [msgs, setMsgs] = useState<Msg[]>([{ role: 'model', text: 'Hi! Ask me about your plan — what to take next, what a course unlocks, or how far along your major is.' }]);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: 'end' }); }, [msgs]);

  const send = async () => {
    const q = text.trim();
    if (!q || busy) return;
    const next: Msg[] = [...msgs, { role: 'user', text: q }];
    setMsgs(next); setText(''); setBusy(true);
    try {
      const r = await fetch('/api/chat', { method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ program, term, terms: terms.map(t => t.courses), messages: next.slice(1) }) });   // slice(1): greeting is not a Gemini turn
      const j = await r.json();
      setMsgs(m => [...m, { role: 'model', text: j.reply ?? j.error ?? 'No reply.' }]);
    } catch {
      setMsgs(m => [...m, { role: 'model', text: 'Could not reach the server.' }]);
    } finally { setBusy(false); }
  };

  return (
    <motion.section key="chat" initial={{ y: 12, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: 12, opacity: 0 }} transition={T.base}
      className="absolute right-4 bottom-4 z-20 flex h-[420px] w-80 flex-col rounded-lg border border-line bg-canvas shadow-1" aria-label="Advisor chat">
      <header className="flex h-9 shrink-0 items-center gap-2 border-b border-line px-3 text-[13px] font-semibold">
        Advisor <span className="text-[11px] font-medium uppercase tracking-wide text-ink-3">Gemini</span>
        <button className={`ml-auto grid h-6 w-6 place-items-center rounded-md text-ink-2 hover:bg-surface-hover hover:text-ink ${ring}`} onClick={onClose} aria-label="Close chat">×</button>
      </header>
      <div className="min-h-0 flex-1 space-y-2 overflow-auto p-3 text-[13px]" role="log" aria-live="polite">
        {msgs.map((m, i) => (
          <p key={i} className={`max-w-[85%] whitespace-pre-wrap rounded-md px-2.5 py-1.5 ${m.role === 'user' ? 'ml-auto bg-accent text-white' : 'bg-surface text-ink'}`}>{m.text}</p>
        ))}
        {busy && <p className="text-[12px] text-ink-3">Thinking…</p>}
        <div ref={end} />
      </div>
      <form className="flex shrink-0 gap-2 border-t border-line p-2" onSubmit={e => { e.preventDefault(); send(); }}>
        <input className={`h-7 min-w-0 flex-1 rounded-md border border-line bg-canvas px-2 text-[13px] placeholder:text-ink-3 hover:border-line-strong focus:border-accent ${ring}`}
          value={text} onChange={e => setText(e.target.value)} placeholder="Ask the advisor…" aria-label="Message" disabled={busy} />
        <button type="submit" className={`h-7 rounded-md bg-accent px-2 text-[13px] font-medium text-white hover:bg-accent-hover disabled:opacity-40 ${ring}`} disabled={busy || !text.trim()}>Send</button>
      </form>
    </motion.section>
  );
}
