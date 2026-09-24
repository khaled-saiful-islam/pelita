"""What every app is given, before its own script runs.

An app is the first artifact somebody puts data into, and the frame it runs in
has an opaque origin -- so `localStorage` throws, a form's default action goes
nowhere useful, and a link to another site would replace the app inside the
panel. None of that is the app's to solve, and a model left to solve it writes
something slightly different every time. So it is solved once, here:

- `PelitaStore` -- `load(defaults)` and `save(data)`. In the panel, what was
  saved comes in with the document and every save goes out by message to the
  panel, which keeps it on the person's account. Opened as a downloaded file,
  the same two calls use that browser's own storage. Anywhere else it simply
  forgets, rather than throwing.
- forms never navigate, and links never leave the frame;
- a small stylesheet after the app's own, at zero specificity, so a grid or
  a long word cannot push the app sideways on a phone.

Everything added is marked `data-pelita`, so it is taken out and put back
exactly when the app is changed, and it keeps the same id each time -- the id
is how a downloaded copy finds what it saved.
"""

from __future__ import annotations

import json
import re
from uuid import uuid4

_OURS = re.compile(
    r"<(script|style)\b[^>]*\bdata-pelita\s*=\s*[\"'](?:store|app|state)[\"'][^>]*>.*?</\1\s*>",
    re.S | re.IGNORECASE,
)
_ID = re.compile(r"var ID = \"([0-9a-f]{12})\";")


def app_id_of(document: str) -> str | None:
    found = _ID.search(document)
    return found.group(1) if found else None


def new_app_id() -> str:
    return uuid4().hex[:12]


def strip_runtime(document: str) -> str:
    return _OURS.sub("", document)


def instrument(document: str, app_id: str | None = None) -> str:
    """The app with its runtime in front of it and its guard behind it.

    Idempotent: an app changed ten times carries one runtime, and keeps the id
    it was first given unless it is handed another.
    """
    app_id = app_id or app_id_of(document) or new_app_id()
    document = strip_runtime(document)
    store = _STORE.replace("__ID__", json.dumps(app_id))

    opened = re.search(r"<head\b[^>]*>", document, re.IGNORECASE)
    if opened is not None:
        document = document[: opened.end()] + store + document[opened.end() :]
    else:
        document = store + document

    closed = document.lower().rfind("</head>")
    at = closed if closed != -1 else 0
    return document[:at] + _GUARD + document[at:]


def with_state(document: str, data: object) -> str:
    """The app with what it last saved put in front of everything.

    Done by whoever frames it -- the panel, the share page -- and never
    stored, because the saved data belongs to a person and the document
    belongs to the app.
    """
    given = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    tag = f'<script data-pelita="state">window.__PELITA_STATE__ = {given};</script>'
    opened = re.search(r"<head\b[^>]*>", document, re.IGNORECASE)
    if opened is None:
        return tag + document
    return document[: opened.end()] + tag + document[opened.end() :]


_STORE = """<script data-pelita="store">
(function () {
  var ID = __ID__;
  var KEY = 'pelita-app:' + ID;
  var framed = window.parent !== window;
  var given = window.__PELITA_STATE__;
  var timer = null;
  var pending;

  function local() {
    try { return window.localStorage; } catch (e) { return null; }
  }

  function plain(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
  }

  function copy(value) {
    if (value === undefined) return undefined;
    try { return JSON.parse(JSON.stringify(value)); } catch (e) { return value; }
  }

  function saved() {
    if (given !== undefined) return given;
    var store = local();
    if (!store) return null;
    try {
      var text = store.getItem(KEY);
      return text ? JSON.parse(text) : null;
    } catch (e) { return null; }
  }

  function flush() {
    timer = null;
    var text;
    try { text = JSON.stringify(pending); } catch (e) { return; }
    if (framed) {
      try { window.parent.postMessage({ source: 'pelita-store', data: text }, '*'); } catch (e) {}
      return;
    }
    var store = local();
    if (store) { try { store.setItem(KEY, text); } catch (e) {} }
  }

  window.PelitaStore = {
    load: function (defaults) {
      var found = saved();
      if (found === null || found === undefined) return copy(defaults);
      if (plain(found) && plain(defaults)) {
        var merged = copy(defaults);
        for (var key in found) merged[key] = found[key];
        return merged;
      }
      return found;
    },
    save: function (data) {
      pending = copy(data);
      if (timer) clearTimeout(timer);
      timer = setTimeout(flush, 350);
    },
    clear: function () {
      pending = null;
      if (timer) clearTimeout(timer);
      flush();
    }
  };

  window.addEventListener('pagehide', function () {
    if (timer) { clearTimeout(timer); flush(); }
  });

  // A form here never goes anywhere. The app's own submit handler still runs;
  // this only stops the browser following the form's action afterwards.
  document.addEventListener('submit', function (event) { event.preventDefault(); }, true);

  document.addEventListener('click', function (event) {
    var link = event.target && event.target.closest ? event.target.closest('a[href]') : null;
    if (!link) return;
    var href = link.getAttribute('href') || '';
    if (href === '#' || href === '') { event.preventDefault(); return; }
    if (href.charAt(0) === '#') return;
    // Inside a frame, anywhere else would replace the app with somebody
    // else's page. On its own, in a tab, a link is a link.
    if (framed && !/^(mailto:|tel:)/i.test(href)) event.preventDefault();
  }, true);
})();
</script>"""

_GUARD = """<style data-pelita="app">
img, video { max-width: 100%; }
:where(#app *) { min-width: 0; }
:where(#app) { overflow-wrap: break-word; }
</style>"""
