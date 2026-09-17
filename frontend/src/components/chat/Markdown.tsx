import { memo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { cn } from '@/lib/utils'
import { isCitationLabel, linkCitations } from '@/lib/citations'
import { Citation } from './Citation'
import type { Source } from '@/hooks/useChat'

/**
 * Renders assistant output.
 *
 * Every element is styled against theme tokens rather than a typography plugin,
 * so a rebrand does not have to reach in here. Memoised because a streaming
 * message re-renders on every token and re-parsing the whole document each time
 * is the difference between smooth and janky.
 */
export const Markdown = memo(function Markdown({
  content,
  sources = [],
}: {
  content: string
  /** When present, inline [n] markers become links to the matching source. */
  sources?: Source[]
}) {
  const body = linkCitations(content, sources)
  const byRank = new Map(sources.map((source) => [source.rank, source]))

  return (
    <div className="text-[0.9375rem] leading-relaxed">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <p className="mb-4 last:mb-0">{children}</p>,
          h1: ({ children }) => <h1 className="mb-3 mt-6 text-xl font-semibold first:mt-0">{children}</h1>,
          h2: ({ children }) => <h2 className="mb-3 mt-6 text-lg font-semibold first:mt-0">{children}</h2>,
          h3: ({ children }) => <h3 className="mb-2 mt-5 font-semibold first:mt-0">{children}</h3>,
          ul: ({ children }) => <ul className="mb-4 ml-5 list-disc space-y-1.5 last:mb-0">{children}</ul>,
          ol: ({ children }) => <ol className="mb-4 ml-5 list-decimal space-y-1.5 last:mb-0">{children}</ol>,
          li: ({ children }) => <li className="pl-1">{children}</li>,
          a: ({ children, href }) => {
            // A citation renders as a numbered chip with a hover preview rather
            // than an underlined number, which would read as part of the
            // sentence.
            if (isCitationLabel(children)) {
              const rank = Number(children)
              const source = byRank.get(rank)
              if (source) return <Citation rank={rank} source={source} />
            }
            return (
              <a
                href={href}
                target="_blank"
                rel="noreferrer noopener"
                className="text-primary underline underline-offset-2 hover:opacity-80"
              >
                {children}
              </a>
            )
          },
          blockquote: ({ children }) => (
            <blockquote className="mb-4 border-l-2 border-border pl-4 text-muted-foreground last:mb-0">
              {children}
            </blockquote>
          ),
          code: ({ className, children, ...props }) => {
            // react-markdown gives inline code no language class.
            const inline = !/language-/.test(className ?? '')
            if (inline) {
              return (
                <code
                  className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.85em]"
                  {...props}
                >
                  {children}
                </code>
              )
            }
            return (
              <code className={cn('font-mono text-[0.85em]', className)} {...props}>
                {children}
              </code>
            )
          },
          pre: ({ children }) => (
            <pre className="mb-4 overflow-x-auto rounded-lg border border-border bg-surface-raised p-3 last:mb-0">
              {children}
            </pre>
          ),
          table: ({ children }) => (
            <div className="mb-4 overflow-x-auto last:mb-0">
              <table className="w-full border-collapse text-sm">{children}</table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border border-border bg-muted px-3 py-1.5 text-left font-medium">
              {children}
            </th>
          ),
          td: ({ children }) => <td className="border border-border px-3 py-1.5">{children}</td>,
          hr: () => <hr className="my-6 border-border" />,
        }}
      >
        {body}
      </ReactMarkdown>
    </div>
  )
})
