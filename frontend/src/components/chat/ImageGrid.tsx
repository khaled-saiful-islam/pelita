import { useState } from 'react'
import { ExternalLink } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ImageResult } from '@/hooks/useChat'

/**
 * Image results, shown above the answer.
 *
 * Each tile links to the page the picture appears on rather than to the image
 * file — a picture with no context is not something a reader can check.
 */
export function ImageGrid({ images }: { images: ImageResult[] }) {
  const visible = images.filter((image) => image.thumbnail_url)
  if (visible.length === 0) return null

  return (
    <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
      {visible.map((image) => (
        <Tile key={`${image.rank}-${image.url}`} image={image} />
      ))}
    </div>
  )
}

function Tile({ image }: { image: ImageResult }) {
  // A thumbnail URL can 404 or be blocked by a referrer policy. Rather than
  // leaving a broken-image icon in the grid, the tile removes itself.
  const [broken, setBroken] = useState(false)
  if (broken) return null

  return (
    <a
      href={image.url}
      target="_blank"
      rel="noreferrer noopener"
      title={image.title}
      className={cn(
        'group/tile relative overflow-hidden rounded-lg border border-border bg-muted',
        'transition-all hover:border-primary/40 hover:shadow',
      )}
    >
      <img
        src={image.thumbnail_url}
        alt={image.title}
        loading="lazy"
        // Do not send the chat URL to whatever host serves the picture.
        referrerPolicy="no-referrer"
        onError={() => setBroken(true)}
        className="aspect-[4/3] w-full object-cover transition-transform group-hover/tile:scale-[1.03]"
      />

      <span
        className={cn(
          'absolute inset-x-0 bottom-0 flex items-center gap-1 px-2 py-1.5',
          'bg-gradient-to-t from-black/75 to-transparent pt-6',
          'text-[0.6875rem] font-medium text-white',
        )}
      >
        <span className="truncate">{image.source || hostOf(image.url)}</span>
        <ExternalLink
          className="size-2.5 shrink-0 opacity-0 transition-opacity group-hover/tile:opacity-80"
          aria-hidden
        />
      </span>
    </a>
  )
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return 'source'
  }
}
