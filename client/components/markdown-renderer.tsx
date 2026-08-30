"use client";

import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface MarkdownRendererProps {
    content: string;
}

export default function MarkdownRenderer({ content }: MarkdownRendererProps) {
    return (
        <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
                p({ children }) {
                    return (
                        <p className="mb-3 last:mb-0 leading-relaxed">
                            {children}
                        </p>
                    );
                },
                strong({ children }) {
                    return (
                        <strong className="font-semibold">{children}</strong>
                    );
                },
                em({ children }) {
                    return <em className="italic">{children}</em>;
                },
                del({ children }) {
                    return (
                        <del className="line-through opacity-75">
                            {children}
                        </del>
                    );
                },
                h1({ children }) {
                    return (
                        <h1 className="mt-4 mb-2 text-xl font-bold border-b border-[var(--border)] pb-1.5 text-[var(--text)]">
                            {children}
                        </h1>
                    );
                },
                h2({ children }) {
                    return (
                        <h2 className="mt-3 mb-2 text-lg font-bold text-[var(--text)]">
                            {children}
                        </h2>
                    );
                },
                h3({ children }) {
                    return (
                        <h3 className="mt-3 mb-1.5 text-base font-semibold text-[var(--text)]">
                            {children}
                        </h3>
                    );
                },
                ul({ children }) {
                    return (
                        <ul className="my-2 ml-5 list-disc space-y-1 text-sm leading-relaxed">
                            {children}
                        </ul>
                    );
                },
                ol({ children }) {
                    return (
                        <ol className="my-2 ml-5 list-decimal space-y-1 text-sm leading-relaxed">
                            {children}
                        </ol>
                    );
                },
                li({ children }) {
                    return <li className="leading-relaxed">{children}</li>;
                },
                blockquote({ children }) {
                    return (
                        <blockquote className="my-3 border-l-4 border-emerald-500/60 bg-[var(--surface-hover)]/40 py-2 px-4 rounded-r-lg italic text-[var(--muted)] text-sm">
                            {children}
                        </blockquote>
                    );
                },
                a({ href, children }) {
                    return (
                        <a
                            href={href}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-sky-400 hover:text-sky-300 underline underline-offset-2 transition-colors"
                        >
                            {children}
                        </a>
                    );
                },
                hr() {
                    return (
                        <hr className="my-4 border-t border-[var(--border)]" />
                    );
                },
                table({ children }) {
                    return (
                        <div className="my-4 overflow-x-auto rounded-xl border border-[var(--border)] bg-[var(--surface)] shadow-sm">
                            <table className="w-full text-left border-collapse text-sm">
                                {children}
                            </table>
                        </div>
                    );
                },
                thead({ children }) {
                    return (
                        <thead className="bg-[var(--surface-hover)] border-b border-[var(--border)]">
                            {children}
                        </thead>
                    );
                },
                tbody({ children }) {
                    return (
                        <tbody className="divide-y divide-[var(--border)]">
                            {children}
                        </tbody>
                    );
                },
                tr({ children }) {
                    return (
                        <tr className="transition-colors hover:bg-[var(--surface-hover)]/40">
                            {children}
                        </tr>
                    );
                },
                th({ children }) {
                    return (
                        <th className="px-4 py-2.5 font-semibold text-[var(--text)] text-xs uppercase tracking-wider">
                            {children}
                        </th>
                    );
                },
                td({ children }) {
                    return (
                        <td className="px-4 py-2.5 text-sm leading-relaxed">
                            {children}
                        </td>
                    );
                },
                pre({ children }) {
                    return (
                        <div className="my-3 overflow-hidden rounded-xl border border-[var(--border)] bg-[#121212] text-xs text-zinc-100 shadow-sm">
                            <pre className="overflow-x-auto p-4 font-mono leading-relaxed">
                                {children}
                            </pre>
                        </div>
                    );
                },
                code({
                    className,
                    children,
                    ...props
                }: React.ComponentPropsWithoutRef<"code"> & {
                    node?: unknown;
                }) {
                    const isCodeBlock =
                        Boolean(className) ||
                        (typeof children === "string" && children.includes("\n"));

                    if (!isCodeBlock) {
                        return (
                            <code
                                className="rounded bg-[var(--surface-hover)] px-1.5 py-0.5 font-mono text-[0.875em] border border-[var(--border)] text-[var(--text)]"
                                {...props}
                            >
                                {children}
                            </code>
                        );
                    }
                    return (
                        <code className={className} {...props}>
                            {children}
                        </code>
                    );
                },
            }}
        >
            {content}
        </ReactMarkdown>
    );
}
