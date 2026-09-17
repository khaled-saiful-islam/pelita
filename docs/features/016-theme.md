# 016 — Theme

## What it does

Light, dark, or follow the system. Every colour in the application comes from
one file, so a fork can restyle the whole thing without touching a component.

## How it works

`frontend/src/styles/theme.css` defines every colour, radius, shadow and layout
dimension as CSS custom properties, and maps them into Tailwind in the same
file. No component hardcodes a colour; they reference tokens like
`bg-surface` and `text-muted-foreground`.

To rebrand: edit the `--accent-*` ramp and the neutrals. That is the change.

### Three states, not two

A toggle with two states cannot express "follow my operating system", which is
what most people actually want.

| choice | `data-theme` | effect |
|---|---|---|
| Light | `light` | Light, even if the OS is dark |
| Dark | `dark` | Dark, even if the OS is light |
| System | *(absent)* | `prefers-color-scheme` decides |

The CSS matches that structure: the light palette is defined on bare `:root`,
the dark palette under `@media (prefers-color-scheme: dark)` guarded by
`:root:not([data-theme="light"])`, and again under `:root[data-theme="dark"]`.
Defining dark only inside the media query would make an explicit light choice
impossible to honour on a dark machine.

`system` also tracks changes live — the provider listens to the media query, so
switching the OS theme updates the app without a reload.

### Storage

The choice is kept in `localStorage`, per browser. Reads and writes are wrapped
in try/catch: private windows and blocked site data both throw, and the theme
should still apply for the session even when it cannot be remembered.

## Configuration

None. This is a per-viewer preference, not a deployment setting.

To change the *default* look, edit `theme.css`.

## How to extend it

- **A different accent**: change the `--accent-50` … `--accent-900` ramp.
- **More themes**: add a `[data-theme="solarized"]` block and an entry in
  `THEMES` in `Settings.tsx`.
- **Per-account themes**: the choice is client-side. Persisting it means a
  column on `users` and reading it in `ThemeProvider`.

## Known limits

- **Per browser, not per account.** Signing in elsewhere starts at "system".
- **A brief flash on first paint.** The attribute is applied after React mounts,
  so a dark-mode user may see one light frame. An inline script in `index.html`
  reading `localStorage` before hydration would remove it, at the cost of
  duplicating the logic in two places.
- **Only light and dark ship.** The structure supports more; the UI offers two.
- **No high-contrast or reduced-transparency variants.**
