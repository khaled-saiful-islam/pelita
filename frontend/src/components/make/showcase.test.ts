import { describe, expect, it } from 'vitest'
import { inOrder, showcaseOf, startWith } from './showcase'

const poster = { name: 'poster', label: 'Poster', description: 'A poster.' }

describe('startWith', () => {
  it('selects the subject, so typing replaces it and keeps the request', () => {
    const { text, selection } = startWith(poster, 'a night market in Ipoh')
    expect(text).toBe('Design a poster for a night market in Ipoh')
    expect(text.slice(...selection)).toBe('a night market in Ipoh')
  })

  it('puts the caret after the opening when there is no example', () => {
    const { text, selection } = startWith(poster)
    expect(selection).toEqual([text.length, text.length])
  })
})

describe('showcaseOf', () => {
  it('has examples for every kind the app ships with', () => {
    for (const name of ['poster', 'slides', 'games', 'website', 'app']) {
      expect(showcaseOf({ name, label: name, description: '' }).examples.length).toBeGreaterThan(1)
    }
  })

  it('still offers something for a kind it has never heard of', () => {
    // Kinds come from the server's registry; a new one must not arrive blank.
    const shown = showcaseOf({ name: 'resume', label: 'Résumé', description: 'A CV.' })
    expect(shown.opening).toBe('Make a résumé about ')
    expect(shown.examples).toEqual(['A CV.'])
  })
})

describe('inOrder', () => {
  it('puts the kinds in the order people ask for them, not the registry’s', () => {
    const names = ['poster', 'games', 'slides', 'website', 'app', 'resume'].map((name) => ({
      name,
      label: name,
      description: '',
    }))
    expect(inOrder(names).map((k) => k.name)).toEqual([
      'poster',
      'slides',
      'website',
      'app',
      'games',
      'resume',
    ])
  })
})
