import { Loader2, Send, User2, Bot } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ChatMessageOut, postSSE } from "../../api/client";
import { Markdown } from "../../components/chat/Markdown";
import { cn } from "../../lib/cn";
import { Button } from "../../components/ui/button";
import { Textarea } from "../../components/ui/textarea";

interface Props {
  initialMessages: ChatMessageOut[];
  endpoint: string;
  onAfterSend?: () => void;
  placeholder?: string;
}

interface UIMessage {
  role: string;
  content: string;
  pending?: boolean;
}

export function StreamingChat({
  initialMessages,
  endpoint,
  onAfterSend,
  placeholder,
}: Props) {
  const [messages, setMessages] = useState<UIMessage[]>(
    initialMessages.map((m) => ({ role: m.role, content: m.content }))
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

function ChatBubble({ message }: { message: UIMessage }) {
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
        {message.content ? (
          isUser ? (
            <div className="whitespace-pre-wrap">{message.content}</div>
          ) : (
            <Markdown streaming={message.pending}>{message.content}</Markdown>
          )
        ) : message.pending ? (
          <div className="flex items-center gap-1 py-1">
            <span className="typing-dot" style={{ animationDelay: "0ms" }} />
            <span className="typing-dot" style={{ animationDelay: "150ms" }} />
            <span className="typing-dot" style={{ animationDelay: "300ms" }} />
          </div>
        ) : null}
      </div>
    </div>
  );
}
