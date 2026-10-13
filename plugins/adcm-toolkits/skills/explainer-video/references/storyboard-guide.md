# Storyboard guide

How to write the one file the model owns: the guion. The recorder turns each step into
a spoken sentence, an on-screen caption, a subtitle and a real click, in that order and on
that clock. Everything below was checked against the recorder with `explainer-record --check`.

You write two kinds of JSON, both strict (an unknown key is an error, not a hint):

- `videos/config.json`, once per project (`templates/config.json.tmpl`). Keys and defaults:
  `pipeline.md`.
- `videos/guiones/NN-slug.json`, one per video (`templates/guion.json.tmpl`).

## Anatomy of a guion

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | two digits, unique (`01`) |
| `slug` | yes | lowercase letters, digits and dashes; the file is named `<id>-<slug>.json` |
| `title` | yes | shown on the title card at the start and in the manifest |
| `route` | yes | path starting with `/`; opened after the setup and before the first frame |
| `profile` | no | a name from `config.profiles`; its `setup` replaces the default `setup` |
| `next` | no | id of the guion that follows; the video ends with a "next: title" card (adds 2 s) |
| `maxSeconds` | no | 10 to 300; the take fails (exit 1) if it runs longer; default is the window's upper bound |
| `blur` | no | CSS selectors blurred for the whole video |
| `tags` | no | free labels |
| `steps` | yes | 3 to 20 steps |

A step:

| Field | Meaning |
|---|---|
| `say` | required; what the voice reads and the subtitle shows; at most 240 characters |
| `sayAs` | what the voice reads instead of `say` (numbers, acronyms, brand names); the subtitle keeps `say`; at most 240 |
| `caption` | text on the top bar; at most 60 characters; stays until another step sets one; `""` clears it |
| `action` | required; one of the actions below |
| `selector` | the target node (required by `click`, `fill`, `select`, `pick`, `upload`, `drag`) |
| `value` | the argument of the action; the only field that accepts placeholders |
| `highlight` | a selector; a ring follows that node during the step |
| `waitFor` | a selector that must be visible after the action (10 s) before the step ends |
| `hold` | extra milliseconds at the end of the step, 0 to 10000 |

## Actions

| `action` | `selector` | `value` | What happens |
|---|---|---|---|
| `none` | none | none | narration only; the cursor steps out of the subtitle's way |
| `click` | target | none | cursor glides to the node, ring on click |
| `fill` | input | text | replaces the field's content at once |
| `type` | optional | text | types character by character (40 ms each) into the focused node; with a selector it clicks it first |
| `select` | `<select>` | option value or label | `selectOption` |
| `press` | optional | key (`Enter`, `Escape`) | with a selector the key goes to that node, otherwise to the page |
| `scroll` | optional | pixels from the top | scrolls the window, or the scrollable node named by the selector |
| `wait` | none | milliseconds (500 if empty) | pure time |
| `pick` | combobox | text | clicks, types, waits for an option (`[role="option"]`), presses Enter |
| `goto` | none | `/path` or http(s) URL | navigates; the host must be in `allowHosts` |
| `mail` | none | address | needs `config.mail.url`; opens the first link to an allowed host in the newest message to that address |
| `upload` | file input | file path or list | paths are relative to the config file's directory |
| `drag` | source | target selector | drags with 25 intermediate moves |
| `mock` | none | `{url, body}` | answers requests matching `url` with `body` as JSON (200) |

`setup` steps (off camera, before recording) use `action`, `selector`, `value` and `waitFor`
only, with the actions `goto click fill type select press wait none`.

## Narration style

- **One idea per step.** One screen change, one sentence or two short ones.
- **Present tense, direct address.** "Haz clic en Nueva factura", not "the user will click".
- **Name what the viewer sees.** The control by its visible label, the result by what
  appears: "Aparece en la lista con el estado Borrador". Never "as you can see".
- **Say only what is on screen at that moment.** The voice leads (below): a sentence that
  describes the next screen is heard before the screen exists.
- **Length.** 60 to 110 characters is a comfortable step (4 to 8 s). Past ~8 s the viewer
  stares at a static screen: split the step.
- **Language of the voice.** The shipped voice speaks Spanish (es-MX); write `say` in
  Spanish. Subtitles come from `say`; you never write subtitles by hand (they are cut at
  sentence ends into 2 lines of 42 characters).
- **No URLs, ids, file paths, emoji or markdown** in `say`. They are read aloud or shown
  verbatim.
- **Numbers, acronyms, brand names:** put the spoken form in `sayAs` ("mil doscientos
  cincuenta dólares"), or map a word once for every video with `config.pronunciation`
  (whole word, case-insensitive; it changes what is heard, never the subtitle).
- **Open and close.** Step 1 is usually `none`: say what the video teaches. The last step
  says what to do next, or set `next` so the video ends on the next title.

## Captions

The caption is a label, not a second subtitle: a noun phrase or a verb phrase of two to
four words ("Nueva factura", "Fecha de vencimiento"), no final period, never a copy of
`say`. Set one on the steps that start a new phase; it stays on screen until replaced.
At most 60 characters. The bar moves aside by itself when a page heading or a header
control sits in its row.

## Selectors

Playwright strings. Verified on playwright-core 1.63.

| Need | Selector | Note |
|---|---|---|
| role and accessible name | `role=button[name="Save"]` | a quoted name is exact and case-sensitive; `[name="save"i]` ignores case; `[name=/save/i]` matches a substring |
| role and level | `role=heading[level=1]` | |
| visible text, substring | `text=Save` | case-insensitive, matches `Save invoice` too |
| visible text, exact | `text="Save"` | |
| text by regex | `text=/^Save invoice$/i` | |
| CSS | `css=.status-badge`, `[data-testid="save"]` | a bare CSS selector works too |
| CSS with text | `button:has-text("Save")` | |
| scope with `>>` | `nav >> text=Home` | each part searches inside the previous match |
| position | `li >> nth=1` | zero-based; last resort |
| XPath | `xpath=//button[1]` | last resort |

Not available as strings: `label=`, `placeholder=` and the `getBy...` methods. Use
`role=textbox[name="Amount"]` or `[placeholder="Amount"]`.

Prefer, in this order: role and name, test id, exact visible text, CSS class, position.
A selector that matches several nodes does not fail: the recorder takes the first one, so a
sloppy selector can click the wrong thing without an error. `--dry` is how you find out.

## Waiting and holding

- `waitFor` after every action that changes the screen (navigation, opening a dialog,
  saving). The step does not end until the node is visible; a hidden node for 10 s fails
  the take.
- `hold` when the viewer needs time to read the result (400 to 1500 ms). It adds to the
  step; it does not delay the voice.
- `wait` only for pure pauses (an animation you cannot detect). Each millisecond is video.

## Sensitive data

- `blur`: CSS selectors (not role or text selectors, and no `{`, `}` or `;`) for anything personal that appears on
  a screen of the video, such as emails, names and phone numbers.
- Record against demo data from the project's seed or reset, never real records.
- `config.denyList` is a file of patterns (one per line, `#` comments allowed) that must
  never appear in the guion, the subtitles or the dom dump; `--verify` reports `file:line`
  hits. It checks text, not pixels: `blur` is what hides pixels.
- Secrets and sign-in credentials: only `{{env:VAR}}` (below).

## Placeholders

Only inside `value` (and `setup` values), and only when the value is a string. `--check` rejects them in `say`, `sayAs`,
`caption`, `selector`, `highlight` and `waitFor`, in a list or object value (`upload`, `mock`), and rejects any other `{{...}}`.

| Placeholder | Becomes |
|---|---|
| `{{env:VAR}}` | the environment variable `VAR` at run time; exit 2 if it is unset; redacted in console, subtitles, dom dump and timeline, also when a URL shows it percent-encoded |
| `{{today}}` | today's date, `YYYY-MM-DD`, in the config's `timezone` |
| `{{today+N}}`, `{{today-N}}` | N days later or earlier |

## The voice leads

Every step's audio is synthesized before the camera starts, so each step has a known
duration `d`. The camera follows the voice:

1. A step starts at `t`. The caption, subtitle and highlight appear at `t`.
2. The action runs at `t + min(0.6 * d, 3 s)`: in the second half of a short sentence,
   at 3 s of a long one.
3. The step ends at `max(t + d, end of the action) + 0.4 s + hold`. The next step starts
   on the next tenth of a second, so a re-take with the same timings writes the same srt.

What follows for the narration:

- Put the verb and the control first, the result last: "Haz clic en Nueva factura" (the
  click lands in the last words), "Guarda la factura. Aparece en la lista..." (the click
  lands after the first sentence, the second sentence describes the result).
- A step whose action outlasts the voice (`type`, `pick`, `goto`, `mail`) stretches to the
  action; the voice is silent for the rest. Keep those sentences short.
- Never describe a result before the action that causes it, unless the sentence is short
  enough that the action fires inside it.

## Duration budget

`explainer-record --check` prints `OK <id> <slug> <n> steps ~<s>s` and warns when the
estimate leaves `durationWindow` (default 55 to 125 s). The estimate:

```
d       = characters of (sayAs, else say, after pronunciation) * msPerChar / 1000
step    = max(d, min(0.6 * d, 3) + action_s + (waitFor ? 0.3 : 0)) + 0.4 + hold / 1000
total   = 1.75 + sum(step) + 0.5 + (next exists ? 2 : 0)
```

`msPerChar`: edge 70, piper 74, say 68 (at the engine's default rate; `voice.rate` and
`REC_RATE` change the real pace but not the estimate). `action_s`: `none` and `mock` 0;
`wait` its value; `type` 1 + 0.04 per character; `pick` 2.5 + 0.04 per character; `goto`
and `drag` 2; `mail` 3; every other action 1.

Rule of thumb for a voice-bound step: `0.07 s * characters + 0.4 s`. With edge, about 750
characters of narration make 60 s over 12 steps, 1,200 make 90 s over 12 steps, and 1,600
make 120 s over 14 steps. The estimate is a planning aid; the true length comes from the
synthesized clips (the `rec` line prints the voice seconds) and `--verify` enforces the
window. A short feature video can lower the window in the config (`"durationWindow": [15, 60]`).

## Worked example

An invoice form in an app called Acme, narrated in Spanish for the default voice.

`videos/config.json`:

```json
{
  "baseUrl": "http://localhost:5173",
  "durationWindow": [15, 60],
  "setup": [
    { "action": "goto", "value": "/login" },
    { "action": "fill", "selector": "role=textbox[name=\"Correo\"]", "value": "{{env:ACME_EMAIL}}" },
    { "action": "fill", "selector": "role=textbox[name=\"Contraseña\"]", "value": "{{env:ACME_PASSWORD}}" },
    { "action": "click", "selector": "role=button[name=\"Entrar\"]", "waitFor": "role=heading[name=\"Facturas\"]" }
  ]
}
```

The storyboard table, as the executor returns it to the owner:

**01-crear-factura: Crear una factura (~25 s)**

| # | action | narration (say) | caption | est s |
|---|---|---|---|---|
| 1 | none | Bienvenido a Acme Facturación. En este video creas una factura para un proveedor. | Crear una factura | 6.1 |
| 2 | click `Nueva factura` | Empieza con un clic en Nueva factura. | Nueva factura | 3.3 |
| 3 | fill `Monto` = 1250.00 | Escribe el monto: $1,250.00. (heard: "mil doscientos cincuenta dólares") | Captura el monto | 4.0 |
| 4 | fill `Vencimiento` = today + 30 | Fija el vencimiento a treinta días desde hoy. | Fecha de vencimiento | 3.5 |
| 5 | click `Guardar factura`, wait for `Borrador`, highlight the status | Guarda la factura. Aparece en la lista con el estado Borrador. | Guárdala | 5.5 |

English gloss of the narration: 1 Welcome to Acme Billing; in this video you create an
invoice for a provider. 2 Start by clicking New invoice. 3 Type the amount: $1,250.00.
4 Set the due date to thirty days from today. 5 Save the invoice; it appears in the list
with the status Draft.

`videos/guiones/01-crear-factura.json`:

```json
{
  "id": "01",
  "slug": "crear-factura",
  "title": "Crear una factura",
  "route": "/facturas",
  "blur": ["[data-testid=\"correo-proveedor\"]"],
  "tags": ["facturacion"],
  "steps": [
    {
      "say": "Bienvenido a Acme Facturación. En este video creas una factura para un proveedor.",
      "caption": "Crear una factura",
      "action": "none"
    },
    {
      "say": "Empieza con un clic en Nueva factura.",
      "caption": "Nueva factura",
      "action": "click",
      "selector": "role=button[name=\"Nueva factura\"]",
      "waitFor": "role=heading[name=\"Nueva factura\"]"
    },
    {
      "say": "Escribe el monto: $1,250.00.",
      "sayAs": "Escribe el monto: mil doscientos cincuenta dólares.",
      "caption": "Captura el monto",
      "action": "fill",
      "selector": "role=textbox[name=\"Monto\"]",
      "value": "1250.00"
    },
    {
      "say": "Fija el vencimiento a treinta días desde hoy.",
      "caption": "Fecha de vencimiento",
      "action": "fill",
      "selector": "role=textbox[name=\"Vencimiento\"]",
      "value": "{{today+30}}"
    },
    {
      "say": "Guarda la factura. Aparece en la lista con el estado Borrador.",
      "caption": "Guárdala",
      "action": "click",
      "selector": "role=button[name=\"Guardar factura\"]",
      "waitFor": "text=Borrador",
      "highlight": "css=[data-testid=\"estado\"]",
      "hold": 800
    }
  ]
}
```

`explainer-record --check` answers `OK 01 crear-factura 5 steps ~25s`. Step 5 in numbers:
`d` is 4.3 s, the click lands at 2.6 s, and the step lasts `max(4.3, 2.6 + 1 + 0.3) + 0.4 + 0.8`
= 5.5 s. The table's per-step column is that formula per row.

## Before you return

- Every sentence is true of the screen at its step; the action fits the second half.
- `--check` is OK for every guion and no warning leaves the window, or the warning is explained.
- `--dry` exits 0 for every id (the app was up and the data was reset as documented).
- No literal secret, no real personal data, no host outside `allowHosts`.
- You return the table and the command tails, not the JSON.
