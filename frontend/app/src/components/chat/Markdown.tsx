import { Check, Copy } from "lucide-react";
import bash from "highlight.js/lib/languages/bash";
import css from "highlight.js/lib/languages/css";
import go from "highlight.js/lib/languages/go";
import java from "highlight.js/lib/languages/java";
import javascript from "highlight.js/lib/languages/javascript";
import json from "highlight.js/lib/languages/json";
import markdown from "highlight.js/lib/languages/markdown";
import python from "highlight.js/lib/languages/python";
import rust from "highlight.js/lib/languages/rust";
import shell from "highlight.js/lib/languages/shell";
import sql from "highlight.js/lib/languages/sql";
import typescript from "highlight.js/lib/languages/typescript";
import xml from "highlight.js/lib/languages/xml";
import yaml from "highlight.js/lib/languages/yaml";
import { ReactNode, useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";
import { cn } from "../../lib/cn";

const HL_LANGS = {
  bash,
  shell,
  python,
  javascript,
  js: javascript,
  typescript,
  ts: typescript,
  tsx: typescript,
  jsx: javascript,
  json,
  yaml,
  yml: yaml,
  sql,
  go,
  rust,
  java,
  css,
  html: xml,
  xml,
  markdown,
  md: markdown,
};

interface Props {
  children: string;
  className?: string;
  // True when this is the streaming "in-flight" message — we render a blinking caret at the end.
  streaming?: boolean;
}

export function Markdown({ children, className, streaming }: Props) {
  return (
    <div
      className={cn(
        "prose prose-sm max-w-none break-words",
        "prose-p:my-2 prose-p:leading-relaxed",
        "prose-headings:font-semibold prose-headings:tracking-tight prose-headings:mt-3 prose-headings:mb-1.5",
        "prose-h1:text-lg prose-h2:text-base prose-h3:text-sm",
        "prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5",
        "prose-pre:p-0 prose-pre:m-0 prose-pre:bg-transparent",
        "prose-code:before:content-none prose-code:after:content-none",
        "prose-a:text-primary prose-a:underline-offset-2 hover:prose-a:underline",
        "prose-blockquote:border-l-2 prose-blockquote:border-primary/40 prose-blockquote:bg-muted/40 prose-blockquote:py-0.5 prose-blockquote:px-3 prose-blockquote:not-italic prose-blockquote:text-muted-foreground",
        "prose-table:my-3 prose-th:font-medium prose-th:px-2 prose-th:py-1 prose-td:px-2 prose-td:py-1 prose-table:border prose-th:border prose-td:border",
        "prose-hr:my-3",
        // dark mode
        "dark:prose-invert",
        className
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[
          [
            rehypeHighlight,
            { detect: true, ignoreMissing: true, languages: HL_LANGS },
          ],
        ]}
        components={{
          code: CodeRenderer as any,
          pre: PreRenderer as any,
          a: ({ href, children: c }) => (
            <a href={href} target="_blank" rel="noreferrer noopener">
              {c}
            </a>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
      {streaming ? <span className="inline-block w-2 h-4 align-text-bottom bg-current animate-pulse ml-0.5" /> : null}
    </div>
  );
}

// We intercept <pre> so we can attach a copy button + language label.
function PreRenderer({ children }: { children?: ReactNode }) {
  // ReactMarkdown gives us <pre><code class="language-xxx">...</code></pre>
  const child: any = Array.isArray(children) ? children[0] : children;
  const codeProps = child?.props || {};
  const className: string = codeProps.className || "";
  const langMatch = /language-(\w+)/.exec(className);
  const lang = langMatch?.[1];
  const text = extractText(codeProps.children);

  return (
    <CodeBlockShell language={lang} text={text}>
      <pre className="overflow-x-auto rounded-b-lg bg-[#0d1117] text-[13px] leading-relaxed p-3 m-0 hljs">
        <code className={className}>{codeProps.children}</code>
      </pre>
    </CodeBlockShell>
  );
}

// Inline code path. (Block-code paths flow through PreRenderer above.)
function CodeRenderer({
  inline,
  className,
  children,
  ...rest
}: {
  inline?: boolean;
  className?: string;
  children?: ReactNode;
}) {
  if (inline) {
    return (
      <code
        className={cn(
          "rounded bg-muted px-1.5 py-0.5 font-mono text-[0.85em]",
          className
        )}
        {...rest}
      >
        {children}
      </code>
    );
  }
  // Block code is rendered by PreRenderer; just pass through.
  return (
    <code className={className} {...rest}>
      {children}
    </code>
  );
}

function CodeBlockShell({
  language,
  text,
  children,
}: {
  language?: string;
  text: string;
  children: ReactNode;
}) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* ignore */
    }
  }
  return (
    <div className="my-3 overflow-hidden rounded-lg border bg-[#0d1117] not-prose">
      <div className="flex items-center justify-between border-b border-white/10 bg-white/5 px-3 py-1.5">
        <span className="text-[11px] uppercase tracking-wide text-white/60 font-medium">
          {language || "text"}
        </span>
        <button
          type="button"
          onClick={copy}
          className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] text-white/60 hover:text-white hover:bg-white/10 transition-colors"
        >
          {copied ? (
            <>
              <Check className="h-3 w-3" /> Copied
            </>
          ) : (
            <>
              <Copy className="h-3 w-3" /> Copy
            </>
          )}
        </button>
      </div>
      {children}
    </div>
  );
}

function extractText(node: ReactNode): string {
  if (typeof node === "string") return node;
  if (typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(extractText).join("");
  if (node && typeof node === "object" && "props" in (node as any)) {
    return extractText((node as any).props?.children);
  }
  return "";
}
