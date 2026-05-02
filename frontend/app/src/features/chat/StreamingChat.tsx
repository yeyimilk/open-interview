import {
  Bot,
  ChevronDown,
  ChevronRight,
  FileSearch,
  FileText,
  FolderTree,
  Loader2,
  Search,
  Send,
  User2,
  Wrench,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ChatMessageOut, postSSE } from "../../api/client";
import { Markdown } from "../../components/chat/Markdown";
import { VoiceInput } from "../../components/chat/VoiceInput";
import { cn } from "../../lib/cn";
import { Button } from "../../components/ui/button";
import { Textarea } from "../../components/ui/textarea";

interface Props {
  initialMessages: ChatMessageOut[];
  endpoint: string;
  onAfterSend?: () => void;
  placeholder?: string;
}

interface ToolEvent {
  name: string;
  args?: any;
  preview?: string;
  done: boolean;
}

export interface UIMessage {
  role: string;
  content: string;
  pending?: boolean;
  tools?: ToolEvent[];
  voice?: VoiceMeta | null;
}

export interface VoiceMeta {
  duration_s?: number | null;
  wpm?: number | null;
  filler_words?: { word: string; count: number }[];
  pause_count?: number | null;
  tone?: {
    confidence?: number | null;
    energy?: number | null;
    monotone?: number | null;
  };
  language_accuracy?: { score?: number | null; issues?: string[] };
  summary?: string | null;
}

export function StreamingChat({
  initialMessages,
  endpoint,
  onAfterSend,
  placeholder,
}: Props) {
  const [messages, setMessages] = useState<UIMessage[]>(
    initialMessages.map((m) => ({
      role: m.role,
      content: m.content,
      tools: Array.isArray(m.meta?.tools)
        ? (m.meta.tools as ToolEvent[]).map((t) => ({
            name: t.name,
            args: t.args,
            preview: t.preview,
            done: t.done ?? true,
          }))
        : undefined,
      voice: (m.meta?.voice as VoiceMeta) ?? null,
    }))
  );
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  async function send() {
    const content = input.trim();
    if (!content || sending) return;
    setSending(true);
    setMessages((m) => [
      ...m,
      { role: "user", content },
      { role: "assistant", content: "", pending: true },
    ]);
    setInput("");

    try {
      await postSSE(endpoint, { content }, (ev) => {
        if (ev.event === "token") {
          const piece = (ev.data as any)?.content || "";
          setMessages((m) => {
            const copy = [...m];
            const last = copy[copy.length - 1];
            if (last && last.pending) {
              copy[copy.length - 1] = {
                ...last,
                content: last.content + piece,
              };
            }
            return copy;
          });
        } else if (ev.event === "tool_call") {
          const name = (ev.data as any)?.name || "tool";
          const args = (ev.data as any)?.args;
          setMessages((m) => {
            const copy = [...m];
            const last = copy[copy.length - 1];
            if (last && last.pending) {
              const tools = [...(last.tools || []), { name, args, done: false }];
              copy[copy.length - 1] = { ...last, tools };
            }
            return copy;
          });
        } else if (ev.event === "tool_result") {
          const name = (ev.data as any)?.name || "tool";
          const preview = (ev.data as any)?.preview || "";
          setMessages((m) => {
            const copy = [...m];
            const last = copy[copy.length - 1];
            if (last && last.pending && last.tools?.length) {
              const tools = [...last.tools];
              for (let i = tools.length - 1; i >= 0; i--) {
                if (tools[i].name === name && !tools[i].done) {
                  tools[i] = { ...tools[i], preview, done: true };
                  break;
                }
              }
              copy[copy.length - 1] = { ...last, tools };
            }
            return copy;
          });
        } else if (ev.event === "done") {
          const full = (ev.data as any)?.content || "";
          setMessages((m) => {
            const copy = [...m];
            const last = copy[copy.length - 1];
            if (last && last.pending) {
              copy[copy.length - 1] = {
                role: "assistant",
                content: full || last.content,
              };
            }
            return copy;
          });
        } else if (ev.event === "error") {
          const message =
            (ev.data as any)?.message || "Stream error";
          setMessages((m) => {
            const copy = [...m];
            const last = copy[copy.length - 1];
            if (last && last.pending) {
              copy[copy.length - 1] = {
                role: "assistant",
                content: `(error: ${message})`,
              };
            }
            return copy;
          });
        }
      });
    } catch (e) {
      setMessages((m) => {
        const copy = [...m];
        const last = copy[copy.length - 1];
        if (last && last.pending) {
          copy[copy.length - 1] = {
            role: "assistant",
            content: `(error: ${(e as Error).message})`,
          };
        }
        return copy;
      });
    } finally {
      setSending(false);
      onAfterSend?.();
    }
  }

  function onKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  }

  return (
    <div className="flex flex-col h-[70vh] min-h-[420px]">
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto rounded-xl border bg-muted/30 p-3 md:p-4 space-y-3"
      >
        {messages.length === 0 ? (
          <div className="grid h-full place-items-center text-sm text-muted-foreground">
            Start the conversation below.
          </div>
        ) : (
          messages.map((m, i) => <ChatBubble key={i} message={m} />)
        )}
      </div>
      <div className="mt-3 flex items-end gap-2">
        <Textarea
          rows={2}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKey}
          placeholder={
            placeholder ||
            "Type your message... (Enter to send, Shift+Enter for newline)"
          }
          disabled={sending}
          className="resize-none min-h-[60px]"
        />
        <VoiceInput
          disabled={sending}
          onTranscript={(text) =>
            setInput((cur) => (cur ? `${cur.trimEnd()} ${text}` : text))
          }
        />
        <Button
          onClick={send}
          disabled={sending || !input.trim()}
          className="h-[60px] px-5"
        >
          {sending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Send className="h-4 w-4" />
          )}
        </Button>
      </div>
    </div>
  );
}

function ToolTrace({
  tools,
  pending,
}: {
  tools: ToolEvent[];
  pending: boolean;
}) {
  const [open, setOpen] = useState(true);
  const inProgress = tools.some((t) => !t.done);
  const summary =
    inProgress && pending
      ? labelFor(tools[tools.length - 1])
      : `Inspected project (${tools.length} ${
          tools.length === 1 ? "step" : "steps"
        })`;

  return (
    <div className="mb-2 rounded-lg border bg-muted/40 text-xs">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 hover:bg-accent/40 transition-colors rounded-lg"
      >
        {inProgress && pending ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
        ) : (
          <Wrench className="h-3.5 w-3.5 text-primary" />
        )}
        <span className="flex-1 text-left text-muted-foreground">
          {summary}
        </span>
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
        )}
      </button>
      {open ? (
        <ul className="border-t bg-background/50 px-2.5 py-2 space-y-1.5">
          {tools.map((t, i) => (
            <li
              key={i}
              className="flex items-start gap-2 text-muted-foreground"
            >
              <span className="mt-0.5 shrink-0">{iconFor(t.name)}</span>
              <div className="min-w-0 flex-1">
                <div className="font-mono text-foreground/90 truncate">
                  {labelFor(t)}
                </div>
                {t.preview ? (
                  <div className="truncate text-[11px] text-muted-foreground/80">
                    {t.preview}
                  </div>
                ) : !t.done ? (
                  <div className="text-[11px] italic">running...</div>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function iconFor(name: string) {
  switch (name) {
    case "list_dir":
      return <FolderTree className="h-3.5 w-3.5" />;
    case "read_file":
      return <FileText className="h-3.5 w-3.5" />;
    case "grep":
      return <Search className="h-3.5 w-3.5" />;
    case "tree":
      return <FolderTree className="h-3.5 w-3.5" />;
    default:
      return <FileSearch className="h-3.5 w-3.5" />;
  }
}

function labelFor(t: ToolEvent) {
  const a = t.args || {};
  switch (t.name) {
    case "list_dir":
      return `list_dir("${a.path || ""}")`;
    case "read_file":
      return a.start_line || a.end_line
        ? `read_file("${a.path}", ${a.start_line || 1}-${a.end_line || "?"})`
        : `read_file("${a.path}")`;
    case "grep":
      return a.glob
        ? `grep(/${a.pattern}/, ${a.glob})`
        : `grep(/${a.pattern}/)`;
    case "tree":
      return `tree(depth=${a.max_depth || 3})`;
    default:
      return t.name + "(...)";
  }
}

export function ChatBubble({ message }: { message: UIMessage }) {
  const isUser = message.role === "user";
  return (
    <div
      className={cn(
        "flex items-start gap-3 animate-fade-in",
        isUser && "flex-row-reverse"
      )}
    >
      <div
        className={cn(
          "grid h-8 w-8 shrink-0 place-items-center rounded-full",
          isUser
            ? "bg-primary/10 text-primary"
            : "bg-muted text-muted-foreground"
        )}
      >
        {isUser ? <User2 className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </div>
      <div
        className={cn(
          "max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed shadow-sm",
          isUser
            ? "bg-primary text-primary-foreground rounded-tr-md"
            : "bg-card border rounded-tl-md"
        )}
      >
        {!isUser && message.tools && message.tools.length > 0 ? (
          <ToolTrace tools={message.tools} pending={!!message.pending} />
        ) : null}
        {message.content ? (
          isUser ? (
            <div className="whitespace-pre-wrap">{message.content}</div>
          ) : (
            <Markdown streaming={message.pending}>{message.content}</Markdown>
          )
        ) : message.pending && (!message.tools || message.tools.length === 0) ? (
          <div className="flex items-center gap-1 py-1">
            <span className="typing-dot" style={{ animationDelay: "0ms" }} />
            <span className="typing-dot" style={{ animationDelay: "150ms" }} />
            <span className="typing-dot" style={{ animationDelay: "300ms" }} />
          </div>
        ) : null}
        {isUser && message.voice ? (
          <VoiceMetricsRow voice={message.voice} />
        ) : null}
      </div>
    </div>
  );
}

function VoiceMetricsRow({ voice }: { voice: VoiceMeta }) {
  const wpm = voice.wpm != null ? Math.round(voice.wpm) : null;
  const dur = voice.duration_s != null ? voice.duration_s.toFixed(1) : null;
  const conf =
    voice.tone?.confidence != null
      ? Math.round(voice.tone.confidence * 100)
      : null;
  const fillerTotal = (voice.filler_words || []).reduce(
    (a, f) => a + (f.count || 0),
    0
  );
  const lang =
    voice.language_accuracy?.score != null
      ? Math.round(voice.language_accuracy.score * 100)
      : null;
  const chips: { label: string; value: string }[] = [];
  if (dur != null) chips.push({ label: "dur", value: `${dur}s` });
  if (wpm != null) chips.push({ label: "pace", value: `${wpm} wpm` });
  if (fillerTotal > 0)
    chips.push({ label: "fillers", value: `${fillerTotal}` });
  if (conf != null) chips.push({ label: "confidence", value: `${conf}%` });
  if (lang != null) chips.push({ label: "lang", value: `${lang}%` });
  if (chips.length === 0) return null;
  return (
    <div className="mt-2 -mb-1 flex flex-wrap gap-1.5">
      {chips.map((c) => (
        <span
          key={c.label}
          className="inline-flex items-center gap-1 rounded-full bg-primary-foreground/15 px-2 py-0.5 text-[10px] uppercase tracking-wide"
          title={c.label}
        >
          <span className="opacity-70">{c.label}</span>
          <span className="font-medium tabular-nums">{c.value}</span>
        </span>
      ))}
    </div>
  );
}
