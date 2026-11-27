"use client";

import { useState, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { CheckIcon, CopyIcon } from "@/components/icons";

/* Renders a model's answer as formatted text. Raw HTML in the answer is not rendered
   (react-markdown escapes it), so a model cannot inject markup into the page. */

function textOf(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (node && typeof node === "object" && "props" in node) return textOf((node as { props: { children?: ReactNode } }).props.children);
  return "";
}

function CodeBlock({ children }: { children: ReactNode }) {
  const [copied, setCopied] = useState(false);
  const code = textOf(children).replace(/\n$/, "");
  const language = (() => {
    const child = Array.isArray(children) ? children[0] : children;
    const cls = child && typeof child === "object" && "props" in child ? (child as { props: { className?: string } }).props.className : "";
    return /language-([\w+#-]+)/.exec(cls ?? "")?.[1] ?? "";
  })();

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked */
    }
  }

  return (
    <div className="group/code relative my-4">
      <div className="flex items-center justify-between rounded-t-lg border border-b-0 border-[#3e3e38] bg-[#2a2926] px-3 py-1.5 font-sans text-xs text-[#a8a69c]">
        <span>{language || "code"}</span>
        <button onClick={() => void copy()} className="inline-flex items-center gap-1 hover:text-[#e8e6dc]" aria-label="Copy code">
          {copied ? <CheckIcon size={13} /> : <CopyIcon size={13} />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="code-block !mt-0 !rounded-t-none text-[13px]">{code}</pre>
    </div>
  );
}

const components: Components = {
  p: ({ children }) => <p className="my-3 first:mt-0 last:mb-0">{children}</p>,
  h1: ({ children }) => <h1 className="mb-3 mt-6 text-[1.45rem] font-semibold leading-snug first:mt-0">{children}</h1>,
  h2: ({ children }) => <h2 className="mb-2.5 mt-6 text-[1.25rem] font-semibold leading-snug first:mt-0">{children}</h2>,
  h3: ({ children }) => <h3 className="mb-2 mt-5 text-[1.08rem] font-semibold leading-snug first:mt-0">{children}</h3>,
  h4: ({ children }) => <h4 className="mb-2 mt-4 font-semibold first:mt-0">{children}</h4>,
  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  ul: ({ children }) => <ul className="my-3 list-disc space-y-1.5 pl-6 marker:text-slate-400">{children}</ul>,
  ol: ({ children }) => <ol className="my-3 list-decimal space-y-1.5 pl-6 marker:text-slate-500">{children}</ol>,
  li: ({ children }) => <li className="pl-1">{children}</li>,
  a: ({ children, href }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" className="text-brand-700 underline underline-offset-2 hover:text-brand-600">
      {children}
    </a>
  ),
  blockquote: ({ children }) => <blockquote className="my-3 border-l-2 border-slate-300 pl-4 text-slate-600">{children}</blockquote>,
  hr: () => <hr className="my-5 border-slate-200" />,
  pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
  code: ({ children, className }) =>
    className ? (
      <code className={className}>{children}</code>
    ) : (
      <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[0.85em] text-slate-800">{children}</code>
    ),
  table: ({ children }) => (
    <div className="my-4 overflow-x-auto rounded-lg border border-slate-200 font-sans">
      <table className="w-full border-collapse text-sm">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-slate-50">{children}</thead>,
  th: ({ children }) => <th className="border-b border-slate-200 px-3 py-2 text-left font-semibold text-slate-700">{children}</th>,
  td: ({ children }) => <td className="border-b border-slate-100 px-3 py-2 align-top text-slate-700">{children}</td>,
};

export function Markdown({ text }: { text: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
      {text}
    </ReactMarkdown>
  );
}
