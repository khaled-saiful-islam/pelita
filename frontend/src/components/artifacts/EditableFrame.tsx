import { useEffect, useRef, useState } from 'react'
import { fitScale } from './fit-to-panel'

/**
 * The poster with its words editable, in place.
 *
 * A poster renders with scripts disabled, so nothing outside it can make its
 * text editable — a sandboxed frame is opaque to its parent, which is the
 * entire point of it. Edit mode therefore re-renders the frame with
 * `allow-scripts` and one script that we inject.
 *
 * That script is ours and is never model output. The server's validator
 * guarantees the document carries no script of its own, and the frame still
 * has no `allow-same-origin`, so even this one cannot reach the app, its
 * cookies or its API.
 *
 * The runs are numbered in document order, skipping `<style>`, which is
 * exactly how the server numbers them. The two walks agree, so what was edited
 * against is what gets applied.
 */

export const EDITOR = `
(function () {
  var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
    acceptNode: function (node) {
      if (!node.textContent.trim()) return NodeFilter.FILTER_REJECT
      var tag = node.parentNode && node.parentNode.nodeName
      if (tag === 'STYLE' || tag === 'SCRIPT' || tag === 'NOSCRIPT') return NodeFilter.FILTER_REJECT
      return NodeFilter.FILTER_ACCEPT
    },
  })
  var nodes = []
  var node
  while ((node = walker.nextNode())) nodes.push(node)

  nodes.forEach(function (textNode, index) {
    var span = document.createElement('span')
    span.setAttribute('contenteditable', 'true')
    span.setAttribute('data-run', String(index))
    span.style.outline = 'none'
    span.style.borderRadius = '2px'
    span.textContent = textNode.textContent.trim()
    // Replace the run with an editable span carrying the same words. The
    // padding either side is layout and stays where it was.
    textNode.parentNode.replaceChild(span, textNode)

    span.addEventListener('focus', function () {
      span.style.boxShadow = '0 0 0 2px rgba(59,130,246,.9)'
    })
    span.addEventListener('blur', function () {
      span.style.boxShadow = 'none'
    })
    span.addEventListener('input', function () {
      parent.postMessage(
        { source: 'pelita-edit', index: index, text: span.textContent || '' },
        '*'
      )
    })
    // A poster is one line of words per run; a newline would only break the
    // layout it sits in.
    span.addEventListener('keydown', function (event) {
      if (event.key === 'Enter') event.preventDefault()
    })
  })

  parent.postMessage({ source: 'pelita-edit-ready', count: nodes.length }, '*')
})()
`

function withEditor(html: string): string {
  const tag = `<script>${EDITOR}<\/script>`
  return html.includes('</body>') ? html.replace('</body>', `${tag}</body>`) : html + tag
}

export function EditableFrame({
  html,
  width,
  height,
  title,
  onChange,
}: {
  html: string
  width: number
  height: number
  title: string
  onChange: (index: number, text: string) => void
}) {
  const box = useRef<HTMLDivElement>(null)
  const frame = useRef<HTMLIFrameElement>(null)
  const [scale, setScale] = useState(0)

  const real = { width: width > 0 ? width : 794, height: height > 0 ? height : 1123 }

  useEffect(() => {
    const element = box.current
    if (!element) return
    const fit = () =>
      setScale(fitScale(real, { width: element.clientWidth, height: element.clientHeight }))
    fit()
    const observer = new ResizeObserver(fit)
    observer.observe(element)
    return () => observer.disconnect()
  }, [real.width, real.height])

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      // By frame, not by origin: a sandboxed frame without `allow-same-origin`
      // has an opaque origin and reports "null".
      if (event.source !== frame.current?.contentWindow) return
      const data = event.data as { source?: string; index?: number; text?: string }
      if (data?.source !== 'pelita-edit') return
      if (typeof data.index === 'number') onChange(data.index, data.text ?? '')
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [onChange])

  return (
    <div className="flex min-h-0 flex-1 overflow-hidden p-4">
      <div ref={box} className="flex min-h-0 min-w-0 flex-1 items-center justify-center">
        <div
          style={{
            width: real.width * scale,
            height: real.height * scale,
            visibility: scale > 0 ? 'visible' : 'hidden',
          }}
          className="shrink-0 overflow-hidden rounded-md shadow-lg ring-2 ring-primary"
        >
          <iframe
            ref={frame}
            title={`${title} — editing`}
            srcDoc={withEditor(html)}
            // Scripts, for the editor above. Never `allow-same-origin`: with
            // both, the frame could reach straight back into the app.
            sandbox="allow-scripts"
            referrerPolicy="no-referrer"
            style={{
              width: real.width,
              height: real.height,
              transform: `scale(${scale})`,
              transformOrigin: 'top left',
              border: 0,
              display: 'block',
            }}
          />
        </div>
      </div>
    </div>
  )
}
