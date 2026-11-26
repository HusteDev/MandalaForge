# Credits, Print Gating and Payments Design

**Status:** Draft, awaiting review

**Date:** 2026-10-16

**Scope:** Users keep generating, regenerating rings and saving designs for free. Printing (and any export of the full-resolution design) costs credits. The browser never receives the vector design until it has been paid for, so right-click save, open in new tab, Ctrl+P and view-source no longer yield a printable page. Credits are bought through a hosted checkout. No code changes are made until this spec is approved.

## 1. Where the app is today

These facts drive most of the design.

1. **The full design is in the browser.** `/generate` and `/regenerate-ring` return the complete SVG markup (`app.py`), and `static/script.js` injects it with `mandalaDesign.innerHTML = data.svg`. Anyone can copy it from DevTools, from the network tab, or by calling `/generate` directly.
2. **Saved designs are full SVGs in `localStorage`** (`mandalaGallery`, `script.js:586-600`).
3. **Printing is pure client side:** `preparePrintLayout` clones the live SVG into `#print-root` and calls `window.print()` (`script.js:734-777`).
4. **Auth is client side only.** Firebase Auth (project `husted-dev`) gates `index.html` in the browser, but Flask verifies nothing: every route is open to anyone who can reach the server. The README notes the login flow is not wired up and Flask does not serve `login.html`.
5. **Designs are deterministic.** Seed, parameters and `ring_seeds` rebuild a design exactly, so the server can re-render any design from its parameters alone, as long as the engine has not changed since.
6. There is no database, no server-side user record, and no deployment config in the repo.

Consequence: credit gating is meaningless until the server knows who is calling (section 3) and stops handing out vectors (section 4). Payments are the easy part.

## 2. Threat model and honest limits

| Attack | After this design |
|---|---|
| Right-click > Save image / Open image in new tab | Blocked or yields a low-res watermarked raster |
| Ctrl+P / browser Print menu | Prints a "Buy credits to print" sheet, not the design |
| View source / DevTools Elements / Network tab | Only a watermarked preview raster exists; no SVG, no path data |
| Calling `/generate` from curl | Requires a valid Firebase ID token; still returns only the raster |
| Replaying a paid print URL | URL is signed, per-user and short-lived |
| Screenshot of the preview | **Not preventable.** Mitigated by watermark and preview resolution that prints visibly worse than the paid output |
| Paying once, then sharing the PDF | **Not preventable.** Same as any digital download |

No client-side technique stops a determined user from capturing pixels on their own screen. The goal is that the free path produces a visibly inferior, watermarked page, and the paid path is the only way to get a clean, crisp, full-page print. Every rule below that matters is enforced on the server; the client-side deterrents in section 4.4 only remove the one-click shortcuts.

## 3. Server-side identity

1. The browser sends `Authorization: Bearer <Firebase ID token>` on every API call (`firebase.auth().currentUser.getIdToken()`).
2. Flask verifies it with the Firebase Admin SDK (`firebase-admin`) in a `@require_user` decorator that sets `g.uid` and `g.email`. Missing or invalid token returns 401.
3. Local development keeps working through an explicit env flag, `MANDALAFORGE_DEV_USER=<uid>`, honoured only when `FLASK_DEBUG` is on. This replaces the browser-side localhost bypass for API calls; the page-level bypass can stay.
4. Flask serves `login.html` (fixes README item at line 109).

## 4. Preview protection

### 4.1 Rule

No route returns SVG markup, path data or a print-resolution image to a client unless that design has been paid for by that user.

### 4.2 Server-held designs

`/generate` and `/regenerate-ring` render the SVG as today, then **store it server side** and return a `design_id` instead of markup:

```
POST /generate  ->  {
  design_id, used_seed, params_string, validation, plan, ring_seeds,
  rings: [{index, inner_r, outer_r}],     // for the ring selector overlay
  preview_url: "/designs/<id>/preview.webp"
}
```

The stored SVG is the source of truth for that design, so an engine change later never alters a design someone saved or paid for. Unsaved designs are drafts and expire after 24 hours.

`plan` stays in the response: it lists rings, cells and motif names, not geometry. If review finds it leaks enough to rebuild a design, it is cut to what the UI needs.

### 4.3 Preview raster

`GET /designs/<id>/preview.webp` (owner only) renders the stored SVG to a raster:

1. Longest side 1000 px (a letter page printed from it is about 110 dpi, visibly soft next to the vector print).
2. A tiled diagonal watermark ("MandalaForge preview") drawn over the line art at about 12% opacity, light enough to judge the design, heavy enough to ruin a print. A second faint grid or noise layer inside the white regions makes colouring the free copy unpleasant.
3. `Cache-Control: private, no-store`.
4. Rendered with `resvg-py` (prebuilt wheels on Windows, no system Cairo). CairoSVG is the fallback if resvg mis-renders anything; this is checked in phase 1.

Zoom keeps working on the raster but blurs past 100%. If that proves annoying, a later addition is `GET /designs/<id>/preview.webp?region=…` returning a watermarked 1000 px crop of the zoomed area, so zoom shows detail without ever exposing the whole design at high resolution.

### 4.4 Client-side deterrents

Each of these only removes a shortcut; none is relied on for security.

1. The preview is drawn into a `<canvas>` from a `fetch`ed blob, not an `<img>`, so there is no "Save image as" or "Open image in new tab" entry. The blob URL is revoked after drawing.
2. A transparent overlay `div` sits over the canvas; `contextmenu`, `dragstart` and `selectstart` are cancelled on the preview container; `user-select: none`.
3. `@media print` hides the app and the preview and shows a single "Buy credits to print this design" sheet. Ctrl+P and the browser Print menu therefore print that sheet. `beforeprint` cannot cancel printing, so CSS is the mechanism.
4. Ctrl+S and Ctrl+P keydown are intercepted to open the purchase or print dialog instead. Menus and DevTools bypass this, which is fine because there is nothing printable on the page.

### 4.5 UI that used to read the SVG

1. **Ring selector and highlight** (`prepareRingSelection`, `script.js:263-320`) currently query `#mandala > g[id^="ring-"]`. They switch to the `rings` radii in the response and draw the highlight as an annulus in a separate overlay SVG that contains only two circles.
2. **Gallery thumbnails** use a 200 px watermarked preview from `GET /designs/<id>/thumb.webp`.
3. **Debug bar** keeps showing parameters; it never showed geometry.

### 4.6 Saved designs and the gallery

1. **Save Design** calls `POST /designs/<id>/save`, which clears the draft expiry. The gallery lists `GET /designs` for the signed-in user, so saved designs follow the user across devices.
2. The 12-item cap becomes a per-user server cap of 100 saved designs (adjustable).
3. Migration: on first load after release, `localStorage.mandalaGallery` entries are re-created server side from their saved `params` and `ring_seeds` (the server regenerates the SVG; it never accepts SVG from the client), then the key is deleted. Designs that no longer regenerate identically because the engine changed are imported as they now render.
4. QA tooling (`qa_check.py`, `qa_report.py`, tests) calls the generator directly and is unaffected.

## 5. Credits

### 5.1 What a credit buys

**Default: 1 credit unlocks one design for printing permanently.** After unlocking, the user can print or download that design again at no further cost; regenerating a ring makes a new design that needs its own credit.

The alternative is 1 credit per print job. It earns more from repeat printers but punishes a user whose printer jams. This is the one decision in the spec that changes revenue; see section 10.

### 5.2 Data model (Firestore, project `husted-dev`)

Firestore is chosen because the project already uses Firebase; the Flask server is the only writer (Admin SDK), and security rules deny all client reads and writes to these collections.

```
users/{uid}
  email, created_at, credit_balance: int, stripe_customer_id

users/{uid}/ledger/{entry_id}          append-only
  delta: int (+25, -1, ...), balance_after: int,
  reason: "purchase" | "unlock" | "refund" | "admin_grant" | "signup_bonus",
  ref: checkout_session_id | design_id | refund_id, created_at

designs/{design_id}
  uid, params, ring_seeds, plan, svg (string, 7-90 KB, well under the 1 MB doc limit),
  status: "draft" | "saved", unlocked: bool, unlocked_at,
  created_at, expires_at (drafts only; Firestore TTL policy deletes them)

stripe_events/{event_id}               idempotency record for webhooks
  type, processed_at
```

`credit_balance` is a cache of the ledger sum, updated in the same Firestore transaction as each ledger entry, so it can always be rebuilt and audited.

### 5.3 Unlock

`POST /designs/<id>/unlock` with an `Idempotency-Key` header:

1. In one transaction: read the user and the design; if the design belongs to someone else return 404; if already unlocked return success with no charge; if `credit_balance < 1` return 402 `{error: "no_credits"}`; otherwise decrement the balance, write a `-1 unlock` ledger entry, set `unlocked = true`.
2. The idempotency key makes a double-click charge once.

### 5.4 Paid print and export

`GET /designs/<id>/print.pdf?params_page=0|1` (owner only, 403 unless unlocked) returns a letter-size PDF with the vector design centred, and the optional parameters page that "Include parameters on print" adds today. It is generated from the stored SVG with `svglib` + `reportlab` (pure Python wheels), served `Content-Disposition: inline`, `Cache-Control: private, no-store`.

The Print button then works as follows:

1. Design not unlocked: a dialog shows the balance and "Use 1 credit to unlock and print" or "Buy credits".
2. On unlock, the PDF loads in a hidden `iframe` and `iframe.contentWindow.print()` opens the print dialog directly. Where a browser refuses to print a PDF from an iframe (some mobile browsers), the PDF opens in a new tab instead.

Once paid, the PDF contains real vectors and can be saved; that is the product the user bought.

The existing in-page `#print-root` path is removed.

## 6. Pricing and packs

| Pack | Price | Per credit |
|---|---|---|
| Single credit | $0.50 each | $0.50 |
| 25 credits | $10.00 | $0.40 |
| 100 credits | $25.00 | $0.25 |

Stripe charges 2.9% + $0.30 per card payment in the US. A single $0.50 purchase nets about $0.19 (63% lost to fees); the 25 pack nets $9.41; the 100 pack nets $23.98. $0.50 is also Stripe's minimum charge. Default: the single-credit option is sold as a quantity (1 to 24 at $0.50 each) in one checkout, so a user wanting 5 credits pays one fee, and the UI nudges toward the 25 pack at 10 or more. Raising the single-credit floor (for example a minimum of 3) is a business call listed in section 10.

## 7. Checkout and payments

### 7.1 Provider

**Default: Stripe Checkout (hosted page).** Card data never touches this app, so PCI scope is the minimal SAQ A; Apple Pay, Google Pay and Link come for free; and the integration is three server calls.

Alternative worth knowing: a merchant of record such as Lemon Squeezy or Paddle charges about 5% + $0.50 per transaction but collects and remits US sales tax and EU VAT on digital goods for you. Stripe Tax does the calculation for 0.5% per transaction, but registering and filing in each state remains your job once you cross a state's threshold. For a small US-focused launch, Stripe is cheaper; if you expect meaningful EU sales, a merchant of record removes the tax work.

### 7.2 Stripe objects

One Product "MandalaForge credits" with three Prices, each carrying `metadata.credits`: `price_single` ($0.50, `credits=1`, adjustable quantity 1 to 24), `price_25` ($10, `credits=25`), `price_100` ($25, `credits=100`). Price ids live in env config, never in the client.

### 7.3 Flow

1. User clicks a pack. Client calls `POST /checkout {pack: "single"|"25"|"100", quantity?}`.
2. Server creates a Checkout Session: `mode=payment`, the chosen price, `client_reference_id=uid`, `customer` (created and stored on first purchase), `metadata={uid, pack}`, `success_url=/?checkout=success&session_id={CHECKOUT_SESSION_ID}`, `cancel_url=/?checkout=cancel`. Returns the session URL; the client redirects.
3. **Credits are granted only by the webhook**, never by the success redirect. `POST /stripe/webhook` verifies the `Stripe-Signature` header with the endpoint secret, then on `checkout.session.completed` with `payment_status=paid`, in one transaction: skip if `stripe_events/{event.id}` exists; read the line items' `metadata.credits × quantity`; add a `purchase` ledger entry keyed by the session id; bump the balance; record the event.
4. `checkout.session.async_payment_succeeded` is handled the same way (bank methods); `async_payment_failed` does nothing.
5. On return, the success page polls `GET /me` (balance) for a few seconds until the webhook lands, then shows the new balance.
6. `charge.refunded`: subtract the refunded credits proportionally. If the balance would go negative it is set to 0 and the user is flagged; already-unlocked designs stay unlocked.

### 7.4 UI additions

1. Header shows "Credits: N" next to the email, and a "Buy credits" button.
2. A purchase dialog with the three packs and the per-credit price.
3. A purchase history view from the ledger (date, pack, credits, receipt link from Stripe).

## 8. New and changed routes

| Route | Auth | Purpose |
|---|---|---|
| `POST /generate` | user | Changed: stores draft, returns `design_id` + `preview_url`, no SVG |
| `POST /regenerate-ring` | user | Changed: same; takes `design_id` of the parent |
| `GET /designs/<id>/preview.webp`, `/thumb.webp` | owner | Watermarked rasters |
| `GET /designs` | user | Saved gallery |
| `POST /designs/<id>/save`, `DELETE /designs/<id>` | owner | Gallery management |
| `POST /designs/<id>/unlock` | owner | Spend 1 credit |
| `GET /designs/<id>/print.pdf` | owner, unlocked | Paid print |
| `GET /me` | user | Email, balance |
| `GET /me/ledger` | user | Purchase and spend history |
| `POST /checkout` | user | Create Stripe Checkout Session |
| `POST /stripe/webhook` | Stripe signature | Grant or revoke credits |
| `POST /admin/grant` | admin uid list in env | Manual grants and support fixes |

## 9. Delivery phases

Each phase ends with tests green and a manual check in the browser.

1. **Identity and storage.** `firebase-admin`, `@require_user`, dev-user flag, Flask serves `login.html`, Firestore client and security rules, `users` doc created on first call, `GET /me`. Spike: resvg-py and svglib render three existing `test_output` designs correctly.
2. **Server-held designs and protected preview.** `designs` collection, `/generate` and `/regenerate-ring` return ids, preview and thumbnail rasters with watermark, canvas preview, ring overlay from radii, deterrents of 4.4, print CSS sheet, server gallery and localStorage migration. After this phase no route returns SVG.
3. **Credits and paid print.** Ledger, unlock with idempotency, `print.pdf`, Print button flow, `/admin/grant` so the flow can be tested before payments exist.
4. **Stripe.** Products and prices in test mode, `/checkout`, webhook with signature check and idempotency, refunds, purchase dialog and history, Stripe CLI webhook forwarding documented in `docs/local-development.md`.
5. **Go-live.** Live keys, webhook endpoint registered against the deployed HTTPS URL, Firestore TTL policy on `designs.expires_at`, rate limit on `/generate` (for example 60 per minute per user via `flask-limiter`), terms and refund policy page linked from checkout.

Tests: unit tests for the ledger transaction (no double spend, no negative balance, idempotent unlock), webhook handler against Stripe fixture payloads (duplicate events, unpaid sessions, bad signatures), an assertion that no JSON response from any route contains `<svg` or `<path`, and route tests for 401/403/402.

## 10. Open questions

1. **What does a credit buy?** Default: one credit unlocks a design permanently (reprints free). Alternative: one credit per print.
2. **Single-credit floor.** Default: buy 1 to 24 singles in one checkout. Alternative: minimum of 3 singles to keep fees under 30%.
3. **Free credits on sign-up?** Default: none. A single free credit lets new users see the paid print quality.
4. **Do credits expire?** Default: never.
5. **Where is the app hosted?** The webhook and Firestore credentials need a deployed HTTPS server with secrets (for example Cloud Run in the `husted-dev` project, which keeps Firebase, Firestore and the server under one Google account). Nothing in the repo says where it runs today.
6. **Stripe or a merchant of record?** Default: Stripe Checkout; see 7.1 for the tax trade-off.
