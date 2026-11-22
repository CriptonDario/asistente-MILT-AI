import { Check, Copy } from "lucide-react";
import { type ComponentPropsWithoutRef, isValidElement, memo, useRef, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";

function languageOf(children: unknown): string | null {
  if (!isValidElement<{ className?: string }>(children)) return null;
  const match = /language-([\w+#-]+)/.exec(children.props.className ?? "");
  return match?.[1] ?? null;
}

export function CodeBlock({ children, ...props }: ComponentPropsWithoutRef<"pre">) {
  const ref = useRef<HTMLPreElement>(null);
  const [copied, setCopied] = useState(false);
  const language = languageOf(children);

  const copy = async () => {
    const text = ref.current?.textContent ?? "";
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // El portapapeles puede no estar disponible (contexto inseguro).
    }
  };

  return (
    <div className="group/code my-3 overflow-hidden rounded-xl border border-border bg-code">
      <div className="flex items-center justify-between border-b border-border px-3 py-1.5 text-xs text-muted">
        <span className="font-mono">{language ?? "código"}</span>
        <button
          type="button"
          onClick={copy}
          className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-surface-2 hover:text-text"
          aria-label={copied ? "Copiado" : "Copiar código"}
        >
          {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
          {copied ? "Copiado" : "Copiar"}
        </button>
      </div>
      <pre ref={ref} className="overflow-x-auto p-3 font-mono text-[13px] leading-relaxed" {...props}>
        {children}
      </pre>
    </div>
  );
}

const components: Components = {
  pre: ({ node: _node, ...props }) => <CodeBlock {...props} />,
  a: ({ node: _node, href, children, ...props }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
      {children}
    </a>
  ),
};

/**
 * Markdown de las respuestas. El HTML crudo se descarta (`skipHtml`) y las URL
 * peligrosas (`javascript:`...) las neutraliza el `urlTransform` por defecto.
 */
export const Markdown = memo(function Markdown({ text }: { text: string }) {
  return (
    <div className="prose-milt">
      <ReactMarkdown
        skipHtml
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[[rehypeHighlight, { detect: false }]]}
        components={components}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
});
