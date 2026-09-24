import { useState } from 'react'
import { Download } from 'lucide-react'
import { Button } from '@/components/ui'

/**
 * Saving the poster.
 *
 * A picture by default, because that is what a poster is for — it goes into a
 * message or a feed, and neither takes an HTML file. The document is the
 * second option, for whoever wants to edit it again later.
 *
 * Plain links, not fetch-and-blob: the browser already knows how to save a
 * file the server marked as an attachment.
 */
export function DownloadMenu({
  artifact,
  deck,
  playable,
  site,
  app,
}: {
  artifact: { id: string; version: number }
  deck: boolean
  /** A game: the file is the thing, and there is no picture of it. */
  playable?: boolean
  /** A website: one file with every page in it. */
  site?: boolean
  /** An app: one file, which remembers its data in whatever browser opens it. */
  app?: boolean
}) {
  const fileOnly = playable || site || app
  const [open, setOpen] = useState(false)
  const base = `/api/artifacts/${artifact.id}/download?version=${artifact.version}`

  return (
    <span className="relative">
      <Button
        variant="ghost"
        size="sm"
        onClick={() => setOpen((was) => !was)}
        aria-expanded={open}
        title="Download"
      >
        <Download className="size-4" aria-hidden />
      </Button>
      {open && (
        <>
          <span className="fixed inset-0 z-10" onClick={() => setOpen(false)} aria-hidden />
          <span className="absolute right-0 top-full z-20 mt-1 flex w-44 flex-col overflow-hidden rounded-lg border border-border bg-background py-1 shadow-lg">
            {/* A game has one download, because a picture of one is its first
                frame with nobody playing. The file opens and plays anywhere. */}
            {!fileOnly && (
              <a
                href={base}
                download
                onClick={() => setOpen(false)}
                className="px-3 py-2 text-left text-xs hover:bg-hover"
              >
                <span className="block font-medium">
                  {deck ? 'Slides (PDF)' : 'Picture (PNG)'}
                </span>
                <span className="block text-muted-foreground">
                  {deck ? 'One slide a page, to present or send' : 'To post or send'}
                </span>
              </a>
            )}
            <a
              href={`${base}&format=html`}
              download
              onClick={() => setOpen(false)}
              className="px-3 py-2 text-left text-xs hover:bg-hover"
            >
              <span className="block font-medium">
                {playable
                  ? 'Game (HTML)'
                  : site
                    ? 'Website (HTML)'
                    : app
                      ? 'App (HTML)'
                      : 'Document (HTML)'}
              </span>
              <span className="block text-muted-foreground">
                {playable
                  ? 'One file. Open it in any browser and play'
                  : site
                    ? 'One file with every page in it. Opens in any browser'
                    : app
                      ? 'One file. It remembers its data in the browser you open it in'
                      : 'To edit or print later'}
              </span>
            </a>
          </span>
        </>
      )}
    </span>
  )
}
