import { describe, expect, it } from 'vitest'
import { editableSite, siteLayout, sitePages } from './site'

const SITE = `<!DOCTYPE html><html><head><script data-pelita="route-head">1</script></head><body>
<header><nav><a class="nav-link" href="#/home">Home</a></nav></header>
<main id="site">
<section data-page="home" data-title="Home" aria-label="Home"><section class="section"><h1>Hi</h1></section></section>
<section data-page="menu" data-title="Food &amp; drink" aria-label="Food"><p>Kopi</p></section>
</main>
<script>document.body.insertAdjacentHTML('beforeend', '<p>written by script</p>')</script>
<script data-pelita="router">route()</script>
</body></html>`

describe('sitePages', () => {
  it('reads the pages off the document, in order, by the names the nav uses', () => {
    expect(sitePages(SITE)).toEqual([
      { slug: 'home', title: 'Home' },
      { slug: 'menu', title: 'Food & drink' },
    ])
  })

  it('is empty for something that is not a site', () => {
    expect(sitePages('<html><body><div class="canvas"></div></body></html>')).toEqual([])
  })
})

describe('siteLayout', () => {
  it('lays a desktop site out at a desktop width and shrinks it into a narrow panel', () => {
    // Laid out at the panel's own 640px it would be its tablet layout, which
    // is not what anybody asked to see.
    expect(siteLayout('desktop', 640)).toEqual({ width: 1280, scale: 0.5 })
  })

  it('fills a panel wider than a desktop, the way a browser window would', () => {
    expect(siteLayout('desktop', 1600)).toEqual({ width: 1600, scale: 1 })
  })

  it('shows a phone at its own size, never blown up', () => {
    expect(siteLayout('phone', 900)).toEqual({ width: 390, scale: 1 })
  })

  it('shows nothing until there is room to measure', () => {
    expect(siteLayout('tablet', 0).scale).toBe(0)
  })
})

describe('editableSite', () => {
  const editing = editableSite(SITE, 'window.EDITOR = 1')

  it('takes out the site’s own script, which could write words the server never saw', () => {
    expect(editing).not.toContain('written by script')
  })

  it('keeps the routing, so every page can still be reached and edited', () => {
    expect(editing).toContain('data-pelita="router"')
    expect(editing).toContain('data-pelita="route-head"')
  })

  it('puts the editor in before the router, so a click on a link edits it instead', () => {
    expect(editing.indexOf('window.EDITOR')).toBeLessThan(editing.indexOf('data-pelita="router"'))
    expect(editing).toContain('stopImmediatePropagation')
  })
})
