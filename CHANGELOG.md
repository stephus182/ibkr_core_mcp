# Changelog

All notable changes to `ibkr_core_mcp` are documented here.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Fixed
- **`preview_order` read four keys the whatif does not send, and discarded IBKR's refusal.**
  A preview exists to answer "can this account support this order". It answered `N/A`, and
  when IBKR said no it did not say so at all.

  The tool read `result["commission"]`, `result["equity"]["amount"]`,
  `result["initMarginChange"]` and `result["maintMarginChange"]`. The response carries
  `amount.commission`, `equity.current`, `initial.change` and `maintenance.change`. So four of
  the five rendered lines were `N/A` on **every real call**, while the numbers sat in the
  response — measured live 2026-09-21 on ESZ6: `initial.change` 24,583 and
  `maintenance.change` 18,459, both present, both discarded. Only `equity.change` was read
  correctly.

  Worse, `error` and `warns` were never read. A preview IBKR **refused** rendered identically
  to one it accepted. Measured live the same day on a `BUY 2 ES` this account cannot support:
  IBKR returned *"The Available Funds in your Commodities segment are insufficient … your
  Commodities Net Liquidation Value [43378.26 USD] must exceed the new total initial Margin of
  [49207.72 USD]"* plus three warnings, and the model saw a clean five-line preview with a
  `-4` buying-power effect. This is a read tool — it places nothing, and both gates plus
  IBKR's own placement-time check still stand behind any order — but it reported something
  false about account capacity, in the direction of over-confidence.

  Now: the refusal is printed **before any figure**, warnings are listed with HTML stripped
  (`reply_message_text`, the helper the reply dialogs already use) one per line, and each
  figure comes from the key IBKR uses, rendered as `current → after (change …)`. A block IBKR
  omits is named absent rather than rendered as a number — the same rule the Gate 2 rows
  follow. IBKR's own `"—"` for a commission it will not quote passes through as IBKR's value.

  **The tests could not have caught this.** The mock was invented to match the reader —
  `{"commission": "1.05", "equity": {"amount": 99000}, "initMarginChange": "500",
  "maintMarginChange": "300"}` — and the assertions checked the *request* payload and that the
  text contained `"Order Preview"`, never a rendered figure. A double easier than the real
  thing keeps a broken path green forever. Every preview mock in the suite is now the shape
  captured live, and five tests pin the rendering, the refusal ordering, the discriminating
  case (an accepted preview must not claim a refusal), the warning format and the
  absent-block rule.

- **A bare futures root resolved to an EXPIRED contract for days after each roll.** Measured
  live 2026-09-20, two days after the September roll: `/trsrv/futures` still returned ESU6
  (`ltd` 20260918) among 22 ES rows, and every resolution site took the lowest expiry with no
  comparison against today — `_resolve_snapshot_conid` and `_sorted_with_front_month` here,
  and `order_flow.py` in claudia_ui. So "ES" meant a contract that had stopped trading.

  Two impacts, and the quiet one was worse. An **order** failed safe but late: IBKR answers
  `{"error":"Order is already expired."}` only *after* the proposal is built, Touch ID is taken
  and Gate 2 is approved, so a human authenticated an order that could never work. **Market
  data** failed silently: `get_market_snapshot("ES")` returned the dead contract's stale price,
  81 points from the tradeable one, with no error and no warning — a market fact the model
  states and a user may act on.

  The front month is now the earliest row **still tradeable**, decided by `ltd` (they differ:
  ES Dec-26 reports `expirationDate` 20261218 and `ltd` 20261217, and trading stops at `ltd`).
  A row with **no usable date is kept** — an unknown date is not a claim that a contract
  expired, and dropping it would hide a tradeable contract. Expired rows are still **listed**
  by `get_futures`; they are merely never flagged `front_month`. If every row has passed, the
  resolver returns an honest error naming the latest date rather than resolving a dead contract.

  Live-verified after the fix: of 22 ES rows IBKR returned, the one expired row is no longer
  the front month, `515416632` (ltd 20261217) is, and all 22 remain listed.

  This also de-rots six test fixtures that hardcoded real 2026-09 expiries. They were correct
  when written and silently changed meaning at the roll — the same defect as the code's. Dates
  in fixtures are now computed relative to today. The captured live fixture redacts its date
  fields to `1111111`, which is not a valid `YYYYMMDD`; that was harmless while nothing read
  them and is now given plausible dates so the file keeps testing typed rows rather than
  failing on redaction. The `_resolve_snapshot_conid` docstring claiming `/trsrv/futures`
  "returns all non-expired contracts" is corrected — it was measured false.

  claudia_ui carries the same rule in its own order path; tracked as its Known Gaps #58.

### Added
- **`place_bracket_and_confirm` — a bracket placed in ONE request, behind one Gate 1 and one
  Gate 2, with EVERY ticket's reply answered.** `place_order` / `place_order_and_confirm` are
  neither reused nor modified: they are the live-proven single-order path, and the way to keep a
  proven path proven is not to branch it. One request also means the pair is atomic at IBKR —
  there is no window in which the child is live alone, which is why two independent orders are
  never a substitute.

  **Gate 1 is bound to the whole ticket array, not to the parent.** The scope hashes every leg,
  so a child altered between Touch ID and the POST falls outside the authorization and prompts
  again. That is the defect audit finding SEC-07 closed for the account id, pointed at the child.

  **Every ticket's reply is answered.** IBKR's reply array is index-aligned with the submitted
  ticket array, so the single-order idiom `while response and "id" in response[0]` inspects the
  parent only: a precaution raised against the CHILD would never be shown, never answered, and
  that leg silently dropped — leaving a resting position with no exit, the one outcome a bracket
  exists to prevent. Every entry carrying an `id` is resolved, in index order, back-to-back (IBKR
  503s a reply left pending while other requests are made). A reply id IBKR re-sends after it was
  answered raises rather than looping: each round costs a human dialog, so an unguarded loop would
  prompt forever.

  **It returns the terminal entries — everything IBKR said that was not a question — accumulated
  rather than replaced.** The composition of a *reply's* response for a bracket is **not yet
  measured**: Phase 0 could not settle it, because the whatif previews only the first ticket and
  discards the rest. Both plausible shapes are handled without loss — a reply response repeating
  the whole array does not duplicate a leg, and one covering only its own ticket does not drop the
  other's terminal entry, whose order id the read-back needs. Accumulating is what makes this
  shape-independent; it should not be "simplified" back to replacing the response until a live
  send has settled the question.

  Registered in the security controls rather than left to be noticed: it is the sixth function
  permitted to build an order-write URL, it joins the Gate 2 dialog table and the never-move-the-gates
  rule in `SECURITY.md`, and `tests/security/test_order_write_boundary.py` now reads it from the
  source like the other five — including the transitive probe, whose expected set it joins because
  it opens with `_ensure_accounts_initialized()` exactly as every other write does.

  Two of those controls did **not** fail when the method appeared, because each was parametrized
  over a list written by hand, and a review found the new write silently exempt from both: the
  behavioural half of SEC-02 (a denied Gate 1 sends no order write, over four methods) and the
  body-the-dialog-showed-is-the-body-sent check (over two). Both now exercise the bracket — the
  second with a case of its own, since a bracket's body is an array and the mutation can land on
  the child — and SEC-02's case list is itself asserted to cover every public gated write, so the
  next write cannot be added without either joining the control or failing the suite. This is the
  same hand-written-list gap that let a fifth Gate 2 dialog escape its class-level checks the same
  day; the lists are what keep failing, not the properties.

- **`confirm_bracket_dialog` — Gate 2 for a bracket: ONE dialog carrying the parent and every
  child.** One dialog, not one per leg, is the whole point: two dialogs would permit the parent
  to be sent with the child declined, which is precisely the state a bracket exists to prevent —
  a resting position with no exit. The human approves the pair as one instruction or sends
  nothing. `place_order` / `place_order_and_confirm` / `confirm_order_dialog` are untouched; the
  live-proven single-order path gains no branch.

  **It formats nothing.** Every value on screen comes from `_order_rows`, the same typed row
  builder the place, modify and cancel dialogs use, so the currency rule (ISO code or nothing),
  the price-precision rule, the futures-notional rule and the missing-price wording cannot drift
  between a single order and a bracket leg. This function composes and labels only.

  **The child is shown as held, never as working.** `PreSubmitted` is a working state for a
  single order and a held one for a bracket child, and that difference is the one thing the
  human needs to understand about the second leg.

  **Exactly one notional row, and it names whose it is** — `Parent notional (est.)`. A bracket's
  legs are opposite, so a row called `Total` would be read as their sum; the child's notional is
  left off rather than printed beside the parent's and mentally added.

  **Five refusals, each a refusal and never a correction** (the contract one shared with
  `_bracket_tickets`, see above): no child; a parent carrying no side
  (the opposite-side rule is unverifiable without it, and the banner is the pre-attentive cue);
  a child on the parent's own side; a child carrying no `parentId` (it would reach IBKR as a
  standalone order, live immediately); and a child naming a **different contract** from the
  parent.

  That last one is checked in **two** places, and neither is redundant. `_bracket_tickets` checks
  it with the other structural rules, so the place path refuses before Touch ID rather than after
  it; this dialog checks it again because it is public API callable without that method, and
  because the check has to run before the display keys are inherited. Neither can be replaced by
  a preview: measured live 2026-09-20, a child on a *different instrument* returns a whatif
  response byte-identical to a valid one, because the preview reads the first ticket and discards
  the rest. **A mismatched bracket previews clean.**

  **Display keys are inherited from the parent, and only after that check.** A bracket child is
  the same contract by construction, so a child carrying no `_companyName` / `_multiplier` /
  `_currency` of its own takes the parent's. Measured 2026-09-21 by rendering one ES bracket both
  ways: without inheritance the child's `Symbol` row drops to `ES` where the parent reads
  `ES — ESU6 · SEP26 · expires 2026-09-18`, and its `Quantity` to `1` where the parent reads
  `1 (×50 per contract)` — one instrument, one dialog, two descriptions, with the month and the
  multiplier missing from the leg the human has never seen before. Inheritance fills gaps only, a
  key the child carries always wins, and it runs *after* the contract check so it can never print
  the parent's own name over a mismatched child. (The price rows do not diverge: a bare child
  carries no `_currency` either. An earlier draft of this claimed a `USD` suffix on the child's
  price; that was wrong, and the measurement above replaced it.)

  Two legs of one kind — a scale-out — are kept distinct (`Profit taker`, `Profit taker 2`)
  rather than collapsing onto one set of rows, which would have the human authorise two live
  children having been shown one.

- **`get_bracket_preview` — whatif for a parent + attached children, read-only and ungated.**
  A bracket is one request carrying an *array* of tickets, so it cannot go through
  `get_order_preview`, which posts a single one. `_bracket_tickets` validates IBKR's stated
  link rules first — `cOID` on the parent, `parentId == cOID` on every child, no `cOID` on a
  child — and refuses anything else, because two unlinked tickets are two INDEPENDENT live
  orders and a standalone opposite-side order can open a position rather than close one.
  Display-only `_`-prefixed keys are stripped, as on every order path.

  **The whatif literal still has exactly one builder.** Rather than let a second method spell
  `/orders/whatif` for itself — the copy-paste `test_preview_is_not_execution.py` exists to
  catch — both entry points delegate to a private `_whatif`. So the structural assertion
  stayed a set of size one while the previewable surface grew; it now names `_whatif`.
  Security invariant 2 and its four references in `docs/security-architecture.md`, plus
  `SECURITY.md`'s control inventory, were updated in the same commit. No new *tool*:
  `ClaudeToolkit` exposes nothing that writes, and this adds nothing the model can call.
  Seven tests, including both entry points asserted gate-free.

  Groundwork for claudia_ui's attached-profit-taker work (its Known Gaps #36), Phase 0 —
  the measurement that answers what IBKR's docs leave unsaid about brackets. The write half
  (`place_bracket_and_confirm`, `confirm_bracket_dialog`) is deliberately **not** here.

- **The built wheel is installed and probed before it can be published.** `publish.yml`'s build
  job now runs `scripts/verify_wheel.py` between `twine check` and the artifact upload: a fresh
  venv under `$RUNNER_TEMP`, `pip install dist/*.whl`, `pip check`, then a probe under `python -I`
  from outside the checkout — `ibkr_core_mcp.__file__` must be in the venv, `__version__` and the
  installed metadata must equal `pyproject.toml`'s version, every `__all__` name must resolve, the
  gateway's Dockerfile, `conf.yaml` and shell scripts plus `py.typed` and `_order_dialog.py` must
  be present, and `ibkr_core_mcp.mcp_server` must import once `[server]` is installed from the same
  wheel. Every earlier gate runs against `pip install -e .`, which cannot see a file dropped from
  `package-data`, and an import probe from the repo root resolves to the checkout (measured: the
  dev venv's interpreter reported 2.0.1 from the repo root, via the checkout's `egg-info`, and
  1.2.2 from anywhere else). Watched failing against a wheel with `conf.yaml` deleted and against
  a wrong expected version; passing on the 2.0.1 wheel. The expected version is PEP 440-normalised
  the way setuptools writes it, so a `2.1.0-rc1` in `pyproject.toml` matches the wheel's `2.1.0rc1`.
  No sdist step: `python -m build` already builds the wheel from the sdist. Unit tests:
  `tests/scripts/test_verify_wheel.py`.

- **`[project].version` must be PEP 440 canonical, enforced by a unit test.** setuptools
  normalises when it builds — a pyproject `2.1.0-rc1` ships as `2.1.0rc1` in the wheel filename
  and METADATA, and so in `__version__` and on PyPI (measured with setuptools 83.0.0) — while
  `publish.yml`'s tag step compares `${TAG#v}` to `[project].version` literally and greps
  `CHANGELOG.md` for `^## [$ver]`, and the README pin and `docs/consumers.md` are literal text.
  Measured against that step's own shell: with a pyproject `2.1.0-rc1`, tag `v2.1.0rc1` — the form
  PyPI displays and consumers pin — fails the tag step, and tag `v2.1.0-rc1` passes it and would
  release a wheel spelled differently from its own tag. `scripts/verify_wheel.py` normalises its
  side and runs after the tag step, so it cannot catch this.
  `test_pyproject_version_is_already_pep440_canonical` now refuses a non-canonical version in the
  four gates — at commit time, and in the `gates` job before `build` — which makes every literal
  comparison agree by construction; the tag step keeps its literal comparison and gains a comment
  saying why that is safe. Watched failing against a pyproject saying `2.0.1-rc1`, with a vacuity
  guard for the check itself. Never fired to date: every release so far has been a plain `X.Y.Z`.
  PEP 440 § Normalization:
  https://packaging.python.org/en/latest/specifications/version-specifiers/#normalization

### Changed
- **The "every Gate 2 dialog" controls now enumerate the dialogs structurally.**
  `test_every_gate2_dialog_passes_an_explicit_abandon_label` and
  `test_no_gate2_dialog_offers_two_buttons_sharing_a_first_word` assert over a list written by
  hand, under a comment warning that a control of this kind "has to cover the class or it will
  pass again the next time a dialog is added". Adding a fifth dialog is exactly that moment: it
  would have been silently exempt from both. The list is now itself asserted against the module —
  every public `confirm_*_dialog` must appear in it — so the next dialog cannot be added without
  either joining the controls or failing the suite.

- **The per-process pacing limitation is stated where a user will actually meet it.**
  `EndpointPacer` budgets per process while IBKR's limit is per IP — documented since 2.0.0 in
  `rate_limiter.py`, `docs/gateway-auth-reference.md` and this changelog, none of which the PyPI
  page shows. The README's Quick start now says so; `IBKRRateLimitError`'s message on a 429 names
  the fifteen-minute penalty box and the per-process budget (a 503 claims neither); the tool
  layer's text no longer advises "retry in a few seconds" against a fifteen-minute box; the
  exception's docstring, `docs/mcp-server-reference.md` (the server is one of the processes) and
  `docs/api-reference.md`'s exception table carry the same fact. The fresh-eye review of this
  change then caught two over-statements, both fixed: `IBKRRateLimitError` now carries
  `.status_code` (429 or 503; 0 when unknown — `IBKRAPIError`'s contract) and the tool layer
  branches on it, so a 503 is reported as the gateway being unavailable rather than a penalty
  box; and the README says the pacer *warns* when it cannot pace (it never holds a call past
  65 s) instead of promising that one process never breaks a limit — the 429 texts name that
  in-process cause too. Held by a README guard in `tests/test_config_docs_consistency.py`, two
  `with_retry` message tests, three `_safe_error` tests and one constructor test.

## [2.0.1] — 2026-09-19

First PyPI release: `pip install ibkr-core-mcp`. Packaging and documentation only — no package
code changed since 2.0.0.

### Changed
- `[build-system]` now requires `setuptools>=77`, the real floor for the PEP 639 `license = "MIT"`
  string — first supported in setuptools 77.0.1 (68 and 76.1 both refused to build; the old floor only worked because isolated builds
  resolve the newest setuptools).
- README links are absolute so the PyPI project page renders them; the header states what the
  package is and is not; the install section leads with PyPI; the MCP section names the `[server]`
  extra; the Quick start names Chrome / `IBKR_AUTH_BROWSER` and the session keepalive.
- `.env.example` no longer lists `ANTHROPIC_API_KEY` and states the five-browser allow-list.
- `pyproject.toml`: `Development Status :: 5 - Production/Stable`; Documentation / Source /
  Changelog / Issues / Security URLs; explicit `license-files`.
- sdist no longer ships a partial `tests/` tree (`MANIFEST.in`).
- Releases are published by `.github/workflows/publish.yml` through PyPI Trusted Publishing
  (TestPyPI rehearsal, reviewed `pypi` environment, PEP 740 attestations).
- CI: top-level `permissions: contents: read`, actions pinned by SHA, Python 3.13 lane, Dependabot.
- CONTRIBUTING, CODE_OF_CONDUCT, issue and PR templates added.
- Tracked documents no longer link into the gitignored `docs/plans/` folder (dead links in clones);
  five new documentation guards in `tests/test_config_docs_consistency.py`.

## [2.0.0] — 2026-09-17

The release-readiness audit release: everything since v1.2.2 was audited as one package
(`docs/audits/release-readiness-audit-2026-09-16.md` — 175 findings, 125 closed, 50 written
off, none open; the pre-tag security audit found nothing above the bar). **Major version
because five changes are incompatible**, each marked breaking in its entry below: 29
`IBKRClient` methods return models rather than dicts; `Config.anthropic_api_key` is gone and
`Config.from_env()` no longer requires the key; SSE clients must send the bearer token; a
price alert's `tif` is GTC or GTD only; and `update_delivery_option` takes `device_name` and
`ui_name`.

### Security
Findings of the 2026-09-17 fresh-eye review of the release-readiness branch
(`docs/audits/release-readiness-audit-2026-09-16.md`, Phase 4), each test-first:
- **The committed-file account-number guard covered one length of the class the redactor
  masks (SEC-R6, Medium).** `tests/security/test_published_identifiers.py` scanned every
  tracked file for `U` + exactly seven digits, while `scripts/audit/redact_live_payload.py`
  rewrites `U` + six to nine before the fixture is written — so a six- or eight-digit account
  number would have passed the guard the capture script refuses. Its comment attributed the
  seven-digit shape to `client.py`, whose `_ACCOUNT_ID_RE` is a path-safety allow-list and
  says nothing about length. The guard now matches the redactor's class byte-for-byte, held
  by `test_the_guard_covers_exactly_the_class_the_redactor_masks` (pattern identity plus
  per-length probes) and by fire tests at six, seven, eight and nine digits, each watched
  failing first; the redactor's `\d` became `[0-9]` to match the codebase's rule for every
  digit class. No exposure: the tree was re-scanned under the widened pattern and the only
  new matches are two six-digit test placeholders, now listed as such.
- **One numeric path rule compiled under two names (SEC-R7, Nit).** `client.py` had
  `_ORDER_ID_RE` and `_NUMERIC_PATH_SEGMENT_RE` as the same `^[0-9]+$`, six lines apart, each
  behind its own validator with its own message — the shape by which a fix reaches one copy
  and not the other. `_ORDER_ID_RE` is gone; `_validate_order_id` goes through
  `_require_numeric` like the conid, page and notification-id validators, and
  `test_documented_controls.py` fails if two names in `client.py` compile one pattern or a
  numeric validator stops sharing the rule. Measured side effect: an `int` order id, which
  used to escape as a raw `TypeError` from `re.fullmatch`, is now accepted as its digits, and
  `True` is refused with the `ConfigError` every other bad value gets. The H-2 strings,
  Unicode digits, `-1`, `1.0`, `None` and `""` are refused as before. `SECURITY.md`'s
  mitigation block and `docs/security-architecture.md`'s invariant-9 row name three regexes
  now, not four.
- **A quoted secret severed before its closing quote passed through redaction whole (SEC-R8,
  Low).** Raised by the pre-tag diff review and reproduced: `{"access_token": "abc123` — the
  shape an error body has when `with_retry`'s or `_decode`'s 400-character preview cuts inside
  the value — matched neither the quoted branch of the identifier rule (no closing quote) nor
  the unquoted one (the opening quote is outside its class), for the JSON and the repr
  spelling alike; the whole forms were scrubbed. No surface in this package is known to
  produce such a body, and the pre-branch pattern had the same gap. The closing quote is now
  optional, so a severed value is consumed to the end of the line — over-redaction, the safe
  direction; ordinary error text is unchanged. Two shapes added to `test_error_redaction.py`'s
  table (20 now), watched failing first.
- **The redirect walker forwarded `Authorization` across origins (SEC-R9, Low).** Raised by the
  same review. `_reject_private_requests` follows each 3xx by hand so that every hop is checked
  (2026-09-16), and `route.fetch` forwards the intercepted request's headers to whatever URL it
  is given — measured with real Chromium against two loopback echo servers: a header a page's
  own script set arrived at the other origin whole. The Fetch standard deletes `Authorization`
  on a cross-origin redirect and Chromium does when it follows the hop itself. From the first
  cross-origin hop on, the walker now passes the request's headers without `Authorization` and
  `Proxy-Authorization` and never restores them; same-origin hops are unchanged, and a
  default-port spelling counts as the same origin. The credential at stake is the crawled
  site's own, sent where that site redirected; the operator's saved logins are cookies, which
  are applied per hop from the context's jar and were never in the forwarded set. Three tests
  in `tests/test_local_browser.py`, the first watched failing; the live suite re-run after.

Findings of the 2026-09-14 recalibration against the OWASP GenAI Security Project's
*A Practical Guide for Secure MCP Server Development* v1.0
(`docs/audits/owasp-mcp-guide-applicability-2026-09-14.md`), each test-first:
- **SSE transport: no client authentication (Medium, local).** `--transport sse` bound loopback
  and validated `Host`/`Origin`, which stops the browser and the LAN but not another process on
  the machine — it needs no DNS trick, just the port, and could open a session and call every
  tool (never an order write, never a credential). Every request must now present this launch's
  bearer token: a fresh `secrets.token_urlsafe(32)` written 0600 to `~/.ibkr_core/mcp_sse_token`
  and never printed, checked with `hmac.compare_digest` before `Host`/`Origin`, on `/sse` as
  well as `/messages/`. `build_sse_app(server, token)` takes the token as a **required**
  argument. **Breaking for SSE clients**, which must now send `Authorization: Bearer <token>`
  (`docs/mcp-server-reference.md` § SSE bearer token); stdio is unaffected. Invariant 10 widened.
- **The operator's home directory appeared in model-facing messages.** `_import_flex_file`'s
  refusal named `/Users/<name>/.ibkr_core` in full, and `redact_error` passed absolute paths
  through — a disclosure the 2026-07-11 audit had noted and left. `redaction.collapse_home`
  rewrites the home directory as `~`, and both surfaces use it; OWASP §6 lists filesystem paths
  beside tokens and stack traces.
- **MCP argument validation was an SDK default with no test (invariant 11, new).** An argument
  set failing a tool's `inputSchema` never reaches a handler, but nothing in this package said
  so and no test sent a malformed argument — while `mcp<2` is capped precisely because 2.0
  removes the decorator carrying that default. `build_server` now states `validate_input=True`,
  and the suite holds that malformed sets never reach `_dispatch`, that no call passes
  `validate_input=False`, and that every name the dispatcher routes is a listed tool (the SDK
  validates no others).

Findings of the 2026-09-13 security architecture audit
(`docs/audits/security-architecture-audit-2026-09-13.md`), each with the regression test that
failed before its fix:
- **Backtest sandbox: arbitrary file read and write from strategy code (A1/A2, High).**
  `df.style.from_custom_template(dir, file)` rendered any file into the un-redacted error
  channel; `df.to_csv(path, header=False)` wrote attacker-chosen bytes to any path as the
  operator; `df.apply("to_csv", …)` and `df.pipe(pd.DataFrame.to_csv, …)` reached the writer by
  name. `_sandboxed_getattr` now applies an **attribute allowlist** to every pandas/numpy object
  and class, the string-function argument of `apply`/`agg`/`transform` faces the same list, and
  the runtime-error text is one line capped at 300 chars. `build_sandbox()` is public so the
  namespace is a testable value (`tests/security/test_sandbox_boundary.py`, 21 tests).
- **SSE transport accepted DNS-rebinding and cross-origin requests (A3).** The MCP SDK disables
  Host/Origin validation when no settings are passed; `build_sse_app` now passes
  `TransportSecuritySettings` allowing loopback only (`test_transport_security.py`).
- **SSRF guard**: parses decimal/hex/octal/short IPv4 literals locally with `inet_aton` before
  DNS (octal `0177.0.0.1` resolved as public while Chromium reads 127.0.0.1) and blocks the RFC
  6598 range `100.64.0.0/10` (Tailscale) and the IPv4 inside an IPv4-mapped IPv6 address
  (`test_ssrf_boundary.py`).
- **One redaction function** (`redaction.redact_error`) for every exception the model layer
  shows or logs; a `requests` exception carries the Flex token in its URL, and three channels
  bypassed `_safe_error` (`test_error_redaction.py`, structural).
- **Unit tests no longer load the operator's `.env`**: `Config()` ran `load_dotenv()` through a
  default factory; an autouse fixture stubs it and removes secret-named variables, and the
  socket block is armed from session start (`test_no_live_io.py`).
- **The body Gate 2 shows is the body sent**: `place_order`/`modify_order`/`get_order_preview`
  copy the order dict at entry (`test_order_write_boundary.py`).
- **Fresh-eye review of the above, same day (six angles), each finding fixed test-first:** the
  sandbox still reached writers through the exposed classes (`pd.Series.apply(series, 'to_csv',
  …)`) and through dict views/generators — `pd.DataFrame`/`pd.Series` are now constructor
  functions and every list-like function spec is checked; the first named-aggregation fix had
  broken `df.close` and `agg(avg=('close', 'mean'))` — column labels pass as data and only the
  function half of a named-aggregation pair is checked; numpy ufunc methods
  (`np.maximum.accumulate`) and `Timestamp.isoformat` are allowed; a missing attribute raises
  `AttributeError` instead of evaluating to `None`; the SSE allowlists accept a port-less `Host`/
  `Origin`; `redact_error` scrubs by shape (`refresh_token=`, `client_secret=`, userinfo, whole
  query strings) and the structural probe also catches `%`/`.format`/`.args`/`log.exception`/
  `exc_info`; `search_site`'s seeder gets an httpx request hook — the browser paths' layer 2 in
  httpx form; the unit-test socket block moved to pytest-socket's own markers applied at
  collection (the session block had left the first live module's fixtures blocked and skipping
  silently); the secret scrub is by prefix and the checked variable set is derived from source;
  the `mcp` floor is 1.10 (`transport_security` did not exist before); the audit scripts parse
  the definitions again; the CI audit uses pip-audit's requirements mode and installs nothing.

### Changed
- **`EndpointPacer` keeps one budget per path and pools every listed verb's limits**
  (API-R11). `ENDPOINT_LIMITS` is keyed by (path, method) as IBKR's table is; the pacer
  keyed by path and silently kept only the first verb's limits. Pooling is deliberate — the
  conservative direction against the fifteen-minute penalty box — and the stricter window
  binds. One matcher scan per request instead of two.
- **BREAKING for consumers — 29 `IBKRClient` methods return models, not dicts** (API-11; the
  detail and the full list are under *Fixed* below). A model is a mapping over exactly what
  IBKR sent — `row["mktValue"]`, `.get`, `in`, `len`, iteration and `dict(row)` are unchanged —
  and it is **not a `dict`**: `isinstance(row, dict)` is False, `json.dumps(row)` needs
  `default=json_default`, and `row == {...}` is False. Measured in ClaudIA on 2026-09-17 with
  rows built from the live fixture, its `parse_orders` kept 0 of 1 orders and
  `parse_contract_info` answered None on `isinstance(row, dict)`, and `parse_positions` and
  `parse_fills` kept 0 of 2 and 0 of 4 on `isinstance(row, Mapping)` — `collections.abc.Mapping`
  has no structural hook, so serving the protocol was not being one — with both suites green
  because every mock is a dict (API-R6). `IBKRResponse` now **derives from
  `collections.abc.Mapping[str, Any]`** — a base class, not a `register()`, because a
  registration is invisible to mypy and ClaudIA's mypy gate was red too, six errors against
  Protocols declared `-> dict[str, Any]` — which repairs every `Mapping` check and every
  `Mapping[str, Any]` annotation without a consumer change; a `dict` check or a `dict`
  annotation is the consumer's to widen. `json_default` and every model are exported from the package root.
  Migration: `docs/consumers.md`.
- **Event Contracts are implemented against IBKR's real endpoints.** `get_event_contracts()`
  and `get_event_contract()` called `/events/contracts` and `/events/show` — paths absent from
  IBKR's entire documentation index, which never worked for any caller, entitled or not. They
  are **removed**, and five methods added against the documented `/forecast/*` endpoints:
  `get_forecast_categories`, `get_forecast_contract`, `get_forecast_market`,
  `get_forecast_rules`, `get_forecast_schedules`. Every path and query parameter was read from
  that endpoint's API-reference page, retrieved with a fabricated control URL in the same batch.

  **None returns a model and none has been executed against a live gateway** — event contracts
  need a subscription the development account does not hold, and this package validates a model
  against a captured response rather than against documentation. The tests pin the request each
  method builds and assert nothing about the response. Audit finding API-R4.

### Removed
- **`anthropic` is no longer a base dependency** — moved to the `dev` extra. **No shipped
  module ever imported it**: the only importer in the repository is
  `scripts/audit/count_tool_tokens.py`, an audit artifact, and `mypy` type-checks `scripts/`,
  so `dev` is where it belongs. Every consumer was installing an SDK this package never calls,
  and `pyproject.toml` therefore claimed this library talks to Anthropic. It does not —
  `ClaudeToolkit` defines tools and the host application owns the model client. Verified by
  blocking the import at the finder level and loading the whole package: it imports cleanly
  and all 44 tools are defined. Audit finding TOOL-R2.

  Only affects consumers that relied on `anthropic` arriving transitively; they should
  declare it themselves, as they already declare every other library they import.

- **BREAKING — `Config.anthropic_api_key` is gone, and `Config.from_env()` no longer requires
  `ANTHROPIC_API_KEY`.** The field was required from the first `Config` commit (`182e483`,
  2026-05-23) and **never had a reader**: zero attribute accesses anywhere in the package, and
  `anthropic` never entered `sys.modules` even with `claude_tools` and `mcp_server` imported.
  `config.py`'s own docstring justified it as "a toolkit with no key cannot do anything at all",
  which was false — `ClaudeToolkit` reads `flex_token`, `gateway_url`, `firecrawl_api_key` and
  `crawl4ai_profiles_dir` and never this one. The cost was real: `mcp_server.main()` calls
  `from_env()`, so **the MCP server refused to start without a key no part of it uses**, and the
  requirement had been routed around three times in two repositories
  (`crawl4ai_profiles_dir_from_env` here; `gateway_preflight.gateway_url` in claudia_ui) rather
  than removed. `docs/mcp-server-reference.md` also told operators to put a real `sk-ant-…` into
  Claude Desktop's plaintext config for that process. Audit finding TOOL-07.

  **The rule this establishes is not Anthropic-specific.** This package makes no model calls —
  `ClaudeToolkit` defines tools and the host application owns the model client — so it carries
  no model credentials from any vendor. `test_config_carries_no_model_vendor_credential` states
  that as a property, so adding `openai_api_key` or `gemini_api_key` later fails the same way.

  **Migration.** Callers using `Config.from_env()` need no change beyond being able to drop the
  variable. Callers constructing `Config(...)` by keyword must delete `anthropic_api_key=`;
  positional constructions shift by one. Anything reading `config.anthropic_api_key` should read
  `os.environ["ANTHROPIC_API_KEY"]`, or simply construct the SDK client with no argument —
  `anthropic.Anthropic()` reads the variable itself, which is what the one known consumer
  already does. `ANTHROPIC_` remains in `tests/conftest.py`'s scrubbed prefixes on purpose: it
  is still the operator's most valuable secret even though this package no longer reads it.

### Added
- **`indicators.vwap(df, anchor, *, tz=None, session_open=None)`** (DATA-R6). The session
  was the calendar day of the frame's index, which for `bars_to_dataframe`'s naive-UTC index
  is the UTC day — the middle of a CME session, measured on ES bars: 4800.00 at 23:59 UTC,
  5000.00 at 00:00 UTC, the earlier prints discarded at 19:00 New York. `tz` names the
  exchange's clock (a naive index is read as UTC, an aware one converted) and `session_open`
  the "HH:MM" a session begins, so `tz="America/New_York", session_open="18:00"` is the CME
  day. The default is unchanged and now documented as the UTC day; `add_indicators` holds
  regular-hours bars only, for which that is the exchange day.
- **Tool capability registry**: every `TOOL_DEFINITIONS` entry and both server-local tools carry
  a `capabilities` frozenset from `claude_tools.CAPABILITIES`; `ClaudeToolkit.tools` strips it
  before schemas reach the API; `tool_capabilities()` returns the map. The suite asserts the set
  declaring `ORDER_EXECUTION` is empty and that every sink a handler's source touches is
  declared — which reclassified `verify_flex_import` (it writes the import manifest).
- **`tests/security/`** — ten files, `security` marker, structural (AST) and canary tests for
  the eleven properties in `SECURITY.md` § Security Regression Suite; each structural checker is
  proven able to fire on a violating snippet.
- **CI gates 5 and 6**: `pip-audit` over `[dev,server,scraper]` (per push and weekly; ignores
  only from `security/pip-audit-ignores.txt`) and `gitleaks` over the pushed range
  (`.gitleaks.toml`). `pip-audit` joins the `dev` extra.
- **MCP `ToolAnnotations`** on every listed tool, derived from its capabilities
  (`mcp_server.tool_annotations`), and `claude_tools.PUBLIC_TOOL_DEFINITIONS` /
  `TOOL_CAPABILITIES` as precomputed constants.
- **`docs/security-architecture.md`** — the living design; `SECURITY.md` corrected against the
  code (Gate 2 mechanism, endpoint path, the `_safe_error` and OAuth snippets, the Flex
  allowlist constant, the `verify=False` inventory, a false Pydantic-validation claim).
- `get_futures`: the front-month row carries `_contract` (local symbol, month, expiry, name,
  multiplier) from the per-conid identity cache — one contract-info call for the row the
  model quotes. Closes claudia_ui gap #37 residual (a): the model had derived `ESU6` from
  the month code and called it confirmed (2026-09-11).
- **One Touch ID per order write** (claudia_ui gap #47, user rule 2026-09-11, as IBKR Mobile
  and TWS ask once per placement, modification or cancellation): `place_order_and_confirm`
  and `modify_order_and_confirm` run Gate 1 once and pass a `human_auth.OrderWriteAuthorization`
  down the chain — bound to the exact body about to be sent (`client._order_write_scope`,
  hashed), 300 s, verified identically at the write and at every precaution reply, fails
  closed, never persisted. Every dialog stays; the reply dialog's title now names its order
  (`confirm_reply_dialog(..., order_label=)`). `place_order` / `modify_order` /
  `_resolve_one_reply` accept `authorization=` (and `scope=`) and behave exactly as before
  without them. Researched against OWASP, NIST SP 800-63B-4, CISA, EU RTS 2018/389 and Apple
  LocalAuthentication — sources in claudia_ui `docs/api-reference.md`.
- `get_futures` rows sorted by expiry per root symbol with `front_month: true` on the
  earliest; `get_market_snapshot` FUT quotes carry `_contract` (local symbol, month token,
  expiry, name, multiplier) from a per-conid cache of `/iserver/contract/{conid}/info`
  (claudia_ui gap #37, 2026-09-10).
- `order_confirm.reply_message_text()` — IBKR reply text with tags stripped, then entities
  unescaped (claudia_ui gap #39, 2026-09-10).
- `IBKRClient.place_order_and_confirm` / `modify_order_and_confirm` accept `reply_log=`, a
  caller-owned list that receives one record per IBKR reply (raw + cleaned text,
  `message_options`, `confirmed`, UTC `at`), including a declined one (claudia_ui gap #38).

### Fixed
The last ten findings of the release-readiness register, closed 2026-09-17 (session 15;
`docs/audits/release-readiness-audit-2026-09-16.md`, Phase 6), each reproduced first and fixed
behind a test watched failing:
- **`_alert_write_error` read the digits `403`, not the status (TOOL-R4, Medium).** A 500
  whose reference number contained them, or a 400 for alert 1403, told the model the alert
  write was permanently blocked upstream and not to retry. Only an `IBKRAPIError` with
  `status_code == 403` gets that text now.
- **`modify_price_alert` sent `outsideRth` as a JSON bool (TOOL-R5).** IBKR documents an
  enum of 0 and 1; create cast it (TOOL-02) and modify overwrote the translated int with the
  caller's bool. Both cast.
- **Three test guards depended on the working directory (API-R7).** Two `client.py` guards
  raised `FileNotFoundError` from outside the repo root, and the assertion-strength scan
  walked `Path("tests")` — from anywhere else it scanned nothing, found nothing, and passed.
  All three are anchored on the module or file they belong to, with a vacuity guard on the
  scan.
- **`with_retry` paced the first attempt only (API-R8).** A 429/503 retry went out after the
  backoff unpaced and unrecorded. Every attempt goes through the pacer.
- **The bar-size grammar was written twice (DATA-R7).** `is_intraday_timeframe` claimed to
  share `periods_for_timeframe`'s parsing while holding its own copy of the pattern. One
  compiled pattern, read by both, held to one copy by a test.
- **Two alert-vocabulary counts disagreed inside one file (TOOL-R6).** "26 keys, two shared"
  and "34 keys, three shared" counted different levels of the same object: 26 top-level plus
  8 inside `conditions[]`, sharing `conditions` and `tif` at the top and `conidex` inside.
  Stated once, held by a test against the live capture and the translation maps.
- **The model oracle had five copies, two matching by substring (API-R9).** `Alert` is inside
  `MTAAlert`; the first non-model class containing a model's name would have split the
  guards. One derivation and one whole-word matcher in `tests/security/structural.py`.
- **A 2xx `{"error": …}` became one-character rows (API-R10).** `get_futures`, `get_stocks`
  and `get_currency_pairs` iterated the message's characters into rows for `parse_many`;
  `get_positions_by_conid` returned `[]`. One `_flatten_buckets` helper serves all four and
  **raises `IBKRAPIError` with IBKR's message** on an error object — a behaviour change for
  a caller that relied on the empty list. The bare-array guard that then tripped on a
  docstring quoting the old pattern now reads code, not prose.

**Every response model was wrong against real IBKR data** (audit finding API-11, filed as a
Nit: "zero of 74 methods return a Pydantic model"). Measuring the six models that already
existed against responses captured from a live gateway found something larger — none of them
worked. `Order` **raised** on a real live order (`orderId` arrives as an `int`, the field
declared `str`); `Contract` **raised** on a `/trsrv/secdef` row (those carry `ticker`, not
`symbol`); `Notification` validated with **every field empty**, because `/fyi/notifications`
returns `D/ID/FC/MD/MS/R` and the model declared `id/date/headline/body/isRead` — zero
overlap; `Trade.time` was always `""` (the key is `trade_time`); `Position` kept 7 of 51 keys
and `AccountSummary` 4 of 108. All six passed their unit tests throughout, because each test
built the model's input by hand.
- **Models are now views over the payload, never a replacement for it.** The new
  `IBKRResponse` base keeps the response exactly as it arrived and serves it through the
  mapping protocol: `position.mkt_value` is the typed, alias-normalised view, while
  `position["mktValue"]`, `dict(position)`, `len(position)` and `for k in position` are what
  IBKR sent. A typed return therefore cannot narrow a 51-key position to seven fields.
  One dict behaviour does not carry over: `model == {...}` is False — compare `dict(model)`.
- **29 methods now return models** (API-11 closed 2026-09-17): `search_contract` and
  `get_secdef` (`Contract`), `get_positions` and `get_all_positions` (`Position`), `get_trades`
  (`Trade`), `get_live_orders` (`Order`), `get_account_summary` (`AccountSummary`),
  `get_notifications` (`Notification`), `get_accounts`, `get_account_meta` and
  `get_subaccounts` (`Account` — the three endpoints were measured key-for-key identical),
  `get_auth_status` (`AuthStatus`), `get_alerts` (`Alert`), `get_mta_alert` (`MTAAlert`),
  `get_watchlists` (`Watchlist`), `get_watchlist` (`WatchlistDetail`), `get_currency_pairs`
  (`CurrencyPair`), `get_secdef_info` (`SecDefInfo`), `get_contract_info` and
  `get_contract_info_and_rules` (`ContractDetails`), `get_contract_rules` (`ContractRules`),
  `get_futures` (`FutureContract`), `get_stocks` (`StockSearchResult`), `get_contract_algos`
  (`Algo`), `get_trading_schedule` (`TradingSchedule`), `get_market_history` and
  `get_market_history_paginated` (`MarketHistory`), `get_option_chain` (`OptionChain`) and
  `get_brokerage_accounts` (`BrokerageSession`). `client.py`'s module docstring enumerates
  them and a test derives the list from `models.py`.

  **Typing everything was never the bar, and the rest are not untyped by accident.** Every
  endpoint in the live capture either returns a model or is listed in
  `tests/test_client_returns_models.py::_NO_MODEL_BY_DESIGN` with the reason — a payload keyed
  by account or currency has no field to name; three captures are empty and a model built on
  an empty capture could only be tested against an invented shape — and
  `test_every_captured_endpoint_is_typed_or_reasoned` fails when a new capture belongs to
  neither set. `MarketHistory.high`/`low` are the reason the rule exists: IBKR sends them as
  `%h/%v/%t` strings, and a `float` field would have raised on every call — silently, because
  `parse_one` answers a validation failure by handing the payload back.
- **A record that will not validate is passed through as the dict it arrived as, never
  dropped** — hence `list[Position | dict[str, Any]]`. And a `null` is IBKR's "not
  applicable", not a malformed value: a search for AAPL returns a bond aggregate whose
  `symbol`, `companyName` and `description` are all null, so a null now falls back to the
  field default and stays readable as `contract["symbol"]`.
- **`AccountSummary` no longer reports P&L the endpoint does not publish** (API-18). The four
  amounts are `float | None`; a key IBKR did not send reads `None`, not `0.0`. Neither
  `unrealizedpnl` nor `realizedpnl` appeared in a 108-key capture and the endpoint's page
  documents none. P&L comes from `get_pnl()` — `/iserver/account/pnl/partitioned`,
  `upnl.{account}.{upl,dpl}`.
- **Every `_normalize` before-validator was dead code** (API-19): each mapped a declared alias
  onto its own field, which `populate_by_name` already did. Found by mutation — breaking
  `Trade`'s alias left the whole suite green. The multi-spelling cases are now `AliasChoices`
  and the validators are gone, 60 lines.
- New: `tests/fixtures/ibkr_live_shapes.json` — **40 endpoints** captured from an
  authenticated gateway (27 on 2026-09-16, 40 on 2026-09-17), plus
  `scripts/audit/capture_live_response_shapes.py` to re-capture and
  `scripts/audit/redact_live_payload.py`, which rewrites every owner-scoped value by default
  while preserving its type and domain. Models are tested against it rather than against
  hand-built dicts. **The first version of this entry read "account numbers rewritten, nothing
  else", and that was the defect**: the fixture was committed to a public repository carrying
  the account holder's name, balances, holdings and executed fills while its account-number
  assertion passed (SEC-13). `tests/security/test_published_identifiers.py` now holds that no
  owner-scoped scalar survives in the committed file.
- **The `get_notifications` tool has never shown a notification** (TOOL-10). Its renderer read
  `isRead` and `headline`/`title`; `/fyi/notifications` sends `R`, `MS`, `MD`, `D`, `ID`, `FC`
  and none of those three, so every notification came out as `- [UNREAD] ?` — right count, no
  titles, read state always wrong. Its test stubbed `{"id", "title", "body", "isRead"}`, a
  payload invented to match the guess. This predates the model work: the handler read raw
  dicts and guessed their keys, the same guess `Notification` made.
- **The price-alert create body was wrong in seven ways** (TOOL-02, widened). IBKR documents
  six Required condition fields; four were wrong or missing: `conid`+`exchange` went as two
  keys where IBKR documents one concatenated `conidex`, `logicBind` and `triggerMethod` were
  absent, and `conditionType: "Price"` was invented (`type: 1` already means Price). Three more
  in the same body: `isSizeCondition` appears in no IBKR page, `outsideRth` was a Python bool
  where IBKR documents an enum of 0/1, and the `tif` enum offered `DAY`, which IBKR does not
  document — it is now `GTC`/`GTD` with a new `expire_time` input, since IBKR documents
  `expireTime` as "Used with a tif of GTD only". **Breaking:** `tif="DAY"` is no longer
  accepted, and `tif="GTD"` now requires `expire_time`.
- **Five files cited a documentation page that no longer exists** (TOOL-08, API-07).
  `v1/endpoints/alerts/create-or-modify-alert.md` returns "# Page Not Found"; the live page is
  `api-reference/trading/trading-alerts/create-alert.md`, which is absent from `llms.txt` and
  so invisible to the index.
- **"Only `>`, `<` and `==` are usable through the gateway" was false** (DOCA-19). It appeared
  in `client.py` and in `docs/ibkr-api-behaviors-reference.md` — twelve lines above that same
  file's table showing those three operators being refused by IBKR with
  `can't recognize fix [>]`. **None of the five documented operators can create an alert**;
  "not blocked by the 403 filter" is not "usable". The standing conclusion is unchanged, only
  the reason a reader would give for it.
- **Two FYI write endpoints contradicted the pages they cite.** `mark_notification_read` sent
  `POST /fyi/notifications/{id}/read`; both of IBKR's documentation families document
  `PUT /fyi/notifications/{notificationId}` with an empty body (API-20). The live test meant to
  cover it accepted success, 400, 404 **and** 423, so it passed whether or not the endpoint
  existed; it is replaced by a local-refusal assertion plus an opt-in live write gated on
  `IBKR_TEST_NOTIFICATION_ID`. `update_delivery_option` conflated two endpoints that share
  neither verb nor parameter style (API-21): `device` is `POST /fyi/deliveryoptions/device`
  with a four-field body, of which two were sent, and `email` is
  `PUT /fyi/deliveryoptions/email?enabled=…`, which a POST-with-body could not reach.
  **Breaking:** `update_delivery_option` now takes `device_name` and `ui_name`, accepts only
  `"device"` or `"email"`, and requires a `device_id` for `"device"`.
- **Invariant 9 held as a claim about three names, not as a property** (SEC-03, SEC-04). It was
  documented as "every path-interpolated identifier passes its regex", had **no test**, and was
  false: an AST enumeration found 36 path interpolations and 10 whose interpolated value was
  never validated — including `get_positions`' page index, in a method that validated its
  account id in the same URL. `tests/security/test_path_identifier_validation.py` now holds the
  property per value, with written exemptions; new validators cover conids, page indices,
  notification ids and the delivery-option allowlist.
  `_resolve_one_reply` applies `_validate_reply_id`, the same check `reply_order` has used
  since 2026-07-11.
- **`_REPLY_ID_RE` is now measured, not inferred** (SEC-11). It was drawn from IBKR's single
  documented example; it has now been checked against **24 reply IDs IBKR actually sent**,
  recovered from the persisted reply logs of real orders placed 2026-09-10/11. All 24 matched,
  and every one was a standard lowercase UUID (8-4-4-4-12) — which the documented example is
  **not**, its third group being six characters. Matching on charset rather than UUID structure
  is what accepts both; tightening it would reject the only example IBKR publishes. Tests pin
  both directions. The IDs are not committed: this repository is public.
- **A failing unread count no longer discards the notification list** (TOOL-12).
  `/fyi/unreadnumber` returned `HTTP 423 {"status":"waiting for reply"}` on four consecutive
  attempts against a healthy gateway while `/fyi/notifications` answered normally; the handler
  called it unguarded. The count now degrades to "unread count unavailable".
- **`ibkr://positions/current` would have stopped carrying positions, silently** (TOOL-11).
  The resource `json.dumps` the client's return and its handler catches every exception, so a
  `Position` reaching it would have produced a successful response reading
  `{"error": "Object of type Position is not JSON serializable"}`. `models.json_default` is
  now passed wherever a response is serialised — **and "wherever" is now a rule read from the
  source, not the sites that happened to break**: `test_every_json_dumps_in_the_tool_layer_can_serialise_a_model`
  fails on any `json.dumps` in `claude_tools.py` or `mcp_server.py` without `default=json_default`
  (25 call sites). `ibkr://accounts` and the `get_alerts` tool had reached the same state on
  this branch a day after TOOL-11 was fixed, because the first fix covered the two sites that
  had broken and the next typed method armed the third.
- **A typed return is a mapping, not a `dict`, and three callers filtered on `isinstance(row,
  dict)`.** Typing `get_futures`, `get_secdef_info` and `get_contract_info` turned 21 futures
  rows into none, made every price report "currency unknown", and dropped the front-month
  `_contract` block — with the unit suite green, because every mock hands its handler a dict.
  Widened to `dict | IBKRResponse`; `tests/claude_tools/test_typed_returns.py` drives the
  affected handlers with models built from the capture. `CLAUDE.md` § Adding a New IBKR
  Endpoint carries both traps as a step. The same two checks in the package's one consumer
  dropped every position, order and fill — API-R6, under *Changed* above.
- **An empty payload did not round-trip (API-R5).** `IBKRResponse` promises `dict(model)` is
  what IBKR sent; for `{}` it answered nine default-valued *field* names, `len()` said 9 and
  `if not response:` flipped to False, because `_payload()` fell back to `model_dump()` on a
  falsy `_raw` and could not tell "IBKR sent `{}`" from "never given a payload". The test is
  `is not None` now; `model_construct()` keeps the fallback.
- **A 2xx with a non-JSON body escaped `IBKRCoreError` (API-15).** The gateway serves an HTML
  page once its session lapses, and `resp.json()` then raised `requests.exceptions.JSONDecodeError`
  straight past the `except IBKRCoreError` every caller is told to write. `client._decode`
  now raises `IBKRAPIError` naming the path and a 400-byte preview; every request helper routes
  through it, `ping` is the one named exemption, and a test fails if a second appears.
- **`modify_price_alert` still offered `tif="DAY"` and could not set an expiry (TOOL-R3).**
  TOOL-02 corrected the vocabulary on `create_price_alert` to IBKR's `GTC`/`GTD` +
  `expire_time` and never reached the modify tool — one fix on one branch of the same body.
  Both tools now share the vocabulary; a modify to `GTD` needs an expiry, from the caller or
  carried over from the alert.
- **`modify_price_alert` and `create_price_alert` say what they cannot do (TOOL-01 closed).**
  Creating or modifying an IBKR alert is not possible through the Client Portal Gateway as
  published — it refuses `>=`/`<=` bodies before IBKR sees them and IBKR refuses the rest —
  and the two descriptions, `README.md`, `docs/tools-reference.md` and the live suite all said
  the tools worked. They now state the block in one phrase, held by a test that also fails the
  day `docs/audits/live-test-log.md` records a passing round trip while the phrase remains.

Four technical indicators disagreed with the definitions they cite. Found by the
2026-09-16 release-readiness audit, which re-derived every one of the 14 against its
source authority instead of checking shapes and bounds. Each divergence below is
measured against a worked example the authority publishes itself — three downloadable
ChartSchool spreadsheets — and every figure is reproducible with
`scripts/audit/indicator_reference_divergence.py` and pinned by
`tests/test_indicators_worked_examples.py`.

**Results computed before this release are not comparable for these indicators.** The
precedent is the 2026-07-07 sortino migration, where pre-migration figures were likewise
accepted as not comparable.

- **`rsi` and `atr`: Wilder smoothing was seeded with the first observation, not the SMA
  of the first `period` values.** `ewm(alpha=1/period, adjust=False)` is a plain EMA
  recursion; Wilder's average is not. Against ChartSchool's published columns RSI was out
  by up to **19.78 points** — bar 15 read 50.75, neutral, where the reference reads 70.53,
  overbought, which is the opposite trading signal — and ATR by up to **22.2%**. Both now
  seed correctly and return NaN through the warm-up instead of printing a value where the
  indicator is undefined; `atr` did so from bar 1. TradingView publishes equivalent Pine
  source that makes the distinction explicit: `pine_rma` seeds `ta.sma(src, length)` while
  `pine_ema` seeds `src`.
- **`bollinger_bands` used the sample standard deviation.** `Series.rolling(n).std()`
  defaults to `ddof=1`; both StockCharts ("StockCharts.com calculates the standard
  deviation for a population") and TradingView (`ta.stdev`'s `biased` defaults to true)
  specify the population form. Every band sat `sqrt(20/19)` = **2.60%** too far from the
  middle at the default period, so every band touch — the signal — was under-reported.
- **`vwap` never reset.** VWAP is defined over a single trading session; this accumulated
  from the first bar of the frame to the last, so on a multi-day intraday frame every
  session carried all the ones before it. It now resets per `anchor` (default `"D"`), and
  raises on a frame with no DatetimeIndex rather than silently running cumulatively.
  `anchor=None` restores the old behaviour explicitly. `add_indicators` reports VWAP only
  for intraday timeframes, because on daily bars it collapses to the bar's typical price —
  "VWAP is not defined for daily, weekly, or monthly periods due to the nature of the
  calculation."
- **`keltner_channels` could not express its own documented default.** The ATR length was
  tied to the EMA length, giving EMA(20) ± 2·ATR(20) where ChartSchool's default triple is
  (20, 2.0, **10**). New `atr_period` argument, defaulting to 10. The two authorities
  genuinely differ here — TradingView's `ta.kc` uses an EMA of true range at the basis
  length — so this one is a documented choice, not a correction.

Verified correct and deliberately left alone: `ema` and `macd` (they match `pine_ema`,
which is what `pinescript.py` emits for TradingView — an SMA seed here would be a wrong
"fix", and a test now guards against it), `stochastic` (the Fast variant, now named in its
docstring), `obv`, `williams_r`, `sma`.

Not one existing test failed when RSI moved by 19.8 points. `tests/test_indicators.py`
asserted shapes and bounds only — `bb_upper >= bb_mid` holds for any non-negative
deviation, so it holds whichever `ddof` you pass — which is the same "control that cannot
fail" pattern this audit found in the live suite and the order-write boundary.

### Fixed
- **`modify_price_alert` sent a body IBKR never asked for, and it read as a create (TOOL-01).**
  The alert-detail response and the create/modify request body are different vocabularies —
  measured live against a real alert: 26 snake_case keys out, 19 camelCase fields expected in,
  and exactly two top-level names (`conditions`, `tif`) in common. The handler posted the
  detail response back with three camelCase keys written on top, so 17 of the 19 documented
  fields were absent by name — `orderId` among them, which is what distinguishes a modify
  from a create. `_alert_detail_to_request` now translates between the shapes, and the
  caller's patch applies to the translated body rather than beside the stale keys.

  Verified live: the translated body posts cleanly and still returns HTTP 403, which
  **eliminates body shape as the cause of the alert-write block** and confirms the `>=`/`<=`
  operator block independently. The owner's alert was unchanged and no duplicate was created.
- **SECURITY.md documented a weaker order-id mitigation than the code implements.** The
  control inventory printed `_ORDER_ID_RE = re.compile(r"^\d+$")` while `client.py`
  compiles `r"^[0-9]+$"`. Python's `\d` matches Unicode decimal digits and `int()` accepts
  them, so the documented pattern admits Arabic-Indic `"١٢٣"` (int reads 123) and mixed
  `"1٢2"` — which int reads as **122**, a different order id than the string appears to
  name. The same file records the fix for that exact gap in its audit log, so it
  contradicted itself, and a reader copying the documented form would have reintroduced it.
  `tests/security/test_documented_controls.py` now fails on drift in either direction;
  it is a documentation-accuracy check, **not** a twelfth invariant.
- **`run_backtest`'s child-exit error blamed the strategy for a caller-side mistake.** The
  sandbox child is started with the `spawn` method, so it re-imports the caller's
  `__main__`; a module-level call re-runs itself in the child and dies with
  `Strategy process exited unexpectedly (exit code 1)`. README's own Backtesting example
  reproduced this when pasted verbatim. The message now names
  `if __name__ == "__main__":` as a possible cause — which matters because `_safe_error`
  shows only `str(exc)`, where Python's own bootstrap guidance does not appear — and the
  example carries the guard.
- **Documentation corrected against the code it describes** (2026-09-16 audit): `docs/README.md`
  stated the gate policy as "re-run for every chained reply", the pre-2026-09-11 rule;
  `README.md` contradicted itself seven lines apart on whether Gate 1 re-prompts;
  `docs/tools-reference.md` documented `search_contract`'s pre-2026-08-05 "JSON array of
  matching contracts" behaviour, which was replaced by resolve-one-or-ask precisely because
  `contracts[0]` for IGV was the Mexican listing; `README.md`'s tool table was missing
  `get_pa_periods` (44 defined, 1 absent); and three documents described the CI dependency
  audit as running "over the full installed tree" when it runs a fresh resolve in
  requirements mode — the distinction that produced this audit's Phase 0 near-miss.
- **Max drawdown ignored any fall that began on the first bar.** `(1 + returns).cumprod()`
  starts the equity curve at the first bar's value, so the starting capital was never a
  peak. Measured:

  | returns | reported | correct |
  |---|---|---|
  | `[-0.50, 0, 0, 0]` | **0.0000** | −0.5000 |
  | `[-0.50, +1.0, 0, 0]` | **0.0000** | −0.5000 |
  | `[-0.10] * 4` | −0.2710 | −0.3439 |

  A strategy that halved on its first bar reported **zero drawdown beside a CAGR of
  −100%**, which cannot both be true. `calmar` returns 0.0 when drawdown is 0.0, so that
  strategy also scored the same Calmar as one that never drew down, and
  `max_drawdown_duration` reported 0 bars under water instead of 4.

  Drawdown is a risk measure and this understated it — the dangerous direction.
  Prepending the initial capital can only raise an early peak, so **every figure computed
  before this fix is understated or exact, never overstated**; 7 stored backtests are
  affected and are not comparable with new ones on this metric.

  Peak *selection* was already correct and is now pinned to Investopedia's published
  worked example (500k → 750k → 400k → 600k → 350k → 800k ⇒ −53.33%, where the interim
  600k peak is not used). That example passes both before and after, which is what makes
  it a usable control.
- **Price alerts could never fire under `--stream` (API-09).** `_stream_loop` subscribed to
  an alert's conid only from inside its `isinstance(item, LiveQuote)` branch. A `LiveQuote`
  is parsed only from an `smd+` frame, and the gateway sends `smd+` only after an
  `smd+{conid}` subscription — so no subscription meant no quote, and no quote meant no
  subscription. The two subscriptions made before the loop are executions and P&L, neither
  of which enters that branch.

  These are local SQLite alerts written by `add_price_alert`, independent of IBKR's own
  alert API (which is separately broken through the gateway), so this was a working feature
  that was silently dead. Reconciliation now runs before the loop and on every message
  regardless of type, and still releases the subscription when an alert is triggered or
  deleted. The loop body had no test at all — `test_stream_loop_retry_on_error` patches
  `_stream_loop` out entirely — which is how this survived; it now has two, and three
  mutants are caught.
- **`EndpointPacer`'s budget is per process; IBKR's limit is per IP (documented, not fixed).**
  Demonstrated on 2026-09-16: a run of short-lived probe scripts against the live gateway,
  each starting with an empty budget, earned HTTP 429 and the documented fifteen-minute
  penalty box although no single process exceeded 50 requests in a minute. A pytest run, a
  script and an MCP server are three processes on one IP, so this is how the package is
  normally used. Closing it needs cross-process state and has not been done; the limitation
  is now stated in `rate_limiter.py` and `docs/gateway-auth-reference.md`, with the
  practical rule: do not run live suites concurrently.
- **`direction=1` was documented as universally broken; it is instrument-specific.** The
  original conid-756733 measurement reproduced exactly, so IBKR changed nothing — but the
  rule had been generalised from one instrument. Re-measured across six: AAPL, MSFT, NVDA
  and IWM return proper forward windows; SPY and QQQ return HTTP 500 in every anchor/period
  combination tried. It is neither security type nor exchange — IWM and SPY are both ARCA
  ETFs. No code path is affected: `get_market_history_paginated` sends `direction=-1`,
  which worked on all six.
- **De-duplication in `get_market_history_paginated` had no real test.** Live chunk seams do
  not overlap (`5d/5min`: 299 bars from the chunks, 299 unique), so the live suite cannot
  exercise it, and in the unit suite a mutant removing it was caught only by accident — its
  early return also skipped an unrelated API-02 assertion. A test that forces an overlapping
  seam now kills both the de-dup and sort-order mutants.
- **A wide intraday history request returned a short answer and only logged it (API-02).**
  `get_market_history_paginated` stops at `_MAX_CHUNKS = 120`; past that it returned a
  well-formed result covering less than asked, announced by a `log.warning` that reaches no
  caller, no model and no cache.

  Verified live 2026-09-16 on AAPL: `1y`/`5min` hit the guard at exactly 120 chunks and
  returned **9,344 bars covering 174 of 365 days — 47.7%**. A backtest labelled "1 year"
  that silently saw under six months draws a conclusion about a period it never had. The
  control in the same session, `90d`/`1min`, finished in 62 chunks at 100.2% coverage and
  correctly carried no warning.

  The response now carries `ibkr_core_warning` naming the period requested, the guard, and
  the date actually reached. **`fetch_market_data` refuses to cache a flagged result**,
  which is the half that mattered: the Drive cache is shared across machines and keyed by
  (symbol, timeframe, period, end), so a partial window stored under `1y` answers every
  later request for a year as though complete — the same persistence that made the
  2026-08-05 `startTime` incident require a cache purge rather than just a code fix.
- **The per-request SSRF guard could raise from its own failure path, intermittently
  killing a crawl.** When a page tears down mid-request, Playwright resolves the
  outstanding route itself; `route.fetch` then raises, the handler's `except` branch called
  `route.abort()`, and abort raised `Route.abort: Route is already handled!` — *from inside
  the except block*, where nothing catches it. It escaped `_reject_private_requests` and
  Playwright re-raised it at teardown as `Browser.close: Route.abort: Route is already
  handled!`.

  This was the intermittent live failure first seen on 2026-09-16 (1 run in 5) and recorded
  then as unidentified, and **it was introduced by that same day's redirect fix** in this
  module. Captured in a full integration sweep by `test_crawl_site_saves_pages_to_drive`.
  Every abort is now best-effort (`_abort_quietly`), logging at debug rather than swallowing
  silently. The SSRF property is unchanged: host checks run before anything is fetched or
  served, so a request that reaches an abort has never been fulfilled. A guard whose failure
  path can itself throw is not a guard.

### Added
- **Five live market-data regression tests** (`tests/test_client_live.py`). API-01 was graded
  Critical and verified only against a stub; a stub encodes what we believe the endpoint does
  and cannot discover the belief is wrong, which is how API-01 happened. These assert the
  properties against the endpoint: the 1000-point cap, that pagination recovers what the cap
  drops (raw 1000 vs paginated 3534, zero lost), bar-size fidelity, that instruments which
  reject `direction=1` still paginate, and that an uppercase period is normalised before it
  reaches IBKR. Reproducible standalone via `scripts/audit/market_data_live_evidence.py`.
- **`rate_limiter.EndpointPacer` — requests are now paced before they are sent.** The module
  was named for pacing and three documents described it as doing token-bucket pacing; it only
  ever retried a 429 after earning one (audit finding API-04). That was not academic.
  Measured live against the gateway on 2026-09-16, `get_market_history_paginated` issued chunk
  requests at **284 per minute** against a published ceiling of 50, and its 120-chunk runaway
  guard would have completed in **~25 seconds** — 2.4x a minute's allowance inside half a
  minute. IBKR answers that with HTTP 429 and a **fifteen-minute penalty box on the IP that
  applies to every endpoint**, against a reactive retry budget of 1 + 2 + 4 = 7 seconds.

  A sliding window per endpoint, wired into every call site through `with_retry(..., path=)`.
  Spaced-out usage never waits. **Bounded by `_MAX_PACING_WAIT` (65 s)**: the 1-req/15-minutes
  endpoints would otherwise block a tool call for 900 s, which is worse than the 429 being
  avoided, and failing outright would break a call that succeeds today — past the cap it warns,
  naming the endpoint and how early the call is, and sends it. Exercised live: the `/pa/transactions`
  warning fired during the integration run and the test passed.
- `analytics.is_intraday_timeframe` — shares `periods_for_timeframe`'s bar-size vocabulary
  and parsing, so the two cannot disagree about what `1m` means (a month, in IBKR notation).
- `indicators.true_range` — True Range as a public function, shared with `atr` so the two
  cannot drift apart.

### Changed
- **`get_live_orders` / `get_orders_raw` read first and prime only on an empty result.** Both
  sent `/iserver/account/orders?force=true` before **every** read, spending two slots of a
  1-req/5-secs endpoint to answer one question. The warmup is real — a fresh brokerage session's
  first read returns an empty array — but it is a **per-session** need that was being paid
  **per call**, and the sibling `get_trades` already handled the identical warmup on
  `/iserver/account/trades` by reading first and retrying on empty.

  Measured live 2026-09-16 on a warm session: three consecutive plain reads, with no
  `force=true` ahead of them, each returned the open order. With pacing enforced,
  `get_live_orders()` went from **5.17 s to 0.35 s**, and from 10.07 s to ~5.0 s when called
  twice back to back — the residue being the published limit itself, which no implementation
  can go under. A cold session still primes; that path is tested in both directions.
- **The per-endpoint rate-limit table moved out of prose and into `rate_limiter.ENDPOINT_LIMITS`.**
  IBKR changed `/iserver/marketdata/history` from "5 concurrent requests" to "10 req/sec or 50
  req/min" at the 2026-08 documentation move, and the link-repointing pass updated the citation
  URL without re-reading the page behind it — leaving a wrong value with a correct-looking source
  beside it (audit finding API-03). Re-read and diffed row by row: **25 of 26 rows agreed and
  that one did not**. There is now one executable table and deliberately no second table in
  prose. (This entry claimed "a test that fails if a second copy reappears"; no such test
  exists — the per-tool one-liners in `docs/tools-reference.md` and `docs/api-reference.md`
  are checked by reading, and the history endpoint's still said "5 concurrent" in both, and
  in `client.py`, until 2026-09-17.)
- `get_market_snapshot`: the price fields reach the model **by name** (`last`, `bid`, `ask`,
  `high`, `low`, `change`, `change_pct`, `volume`, `volume_raw`) from the package's one map,
  `streaming.SNAPSHOT_FIELD_NAMES`; IBKR's numeric codes and server bookkeeping (`server_id`,
  `6119`, `conidEx`, `_updated`, `6509`, `55`) are no longer in the result. Live 2026-09-11 the
  model read `71`/`70` as bid/ask and `84`/`86` as the day's low/high and reasoned about a
  spread that did not exist (claudia_ui gap #52).
- `cancel_order` logs `Gate 1: granted for cancel:<id>` like the place and modify chains, so the
  server log witnesses every fingerprint (2026-09-11: the coverage matrix showed 8 of 12).
- Gate 2 dialogs (claudia_ui gap #42, 2026-09-11): the order detail is rendered in the
  accessory view with **values bold** and labels regular, above the disclaimer, above the
  banner — the reading order the dialog always had — with heights measured so long rows
  wrap; the MODIFY ORDER banner takes the order's colour (green buy / red sell, as IB does);
  a futures price row carries no currency (it is index points — the money is the
  multiplied total).
- `SECURITY.md` §Gate 1 corrected (claudia_ui gap #48): the policy is
  `LAPolicyDeviceOwnerAuthentication` with the device-password fallback, as the code has
  always had it — not biometrics-only; and Gate 1 is documented as once per order write.
- Gate 2: the modify and cancel dialogs render the same typed rows as the place dialog
  (Account / Action / Symbol / Quantity / Order Type / Price / Stop / TIF / Outside RTH /
  Total) plus `Order ID`, a `Changes` row (`<field> <previous> → <new>`, from `_changes`) and
  `Currently at IBKR` (from `_current_description`); raw body keys, nulls and the reason
  blob are gone (claudia_ui gap #40, 2026-09-10). A stop-limit's `auxPrice` now shows as
  its own `Stop` row on every dialog.
- `IBKRClient.modify_order` strips `_`-prefixed display keys before the POST, as
  `place_order` always did.
- **`search_contract` resolves a ticker to exactly ONE listing, with its currency — or asks which one was meant** (2026-08-05). It used to return every match `/iserver/secdef/search` produced, in that endpoint's undocumented order, while its own description told the model to *"use this to discover conids before calling tools that require one"*. Measured live: `contracts[0]` for **IGV was the Mexican listing** (conid 325209548, MEXI), with US/BATS 12658199 second. The consuming app's order path already refused symbol-only proposals, so placement was structurally safe — but the model was still being handed a menu whose first row was the wrong country.

  **Ranking the rows US-first and tagging them `_is_us` was built, measured, and then rejected.** It made the right answer easier to pick but still left the *pick* to the model, so correctness depended on the model reading a flag rather than on the code — the same weakness the original had. A list of plausible conids is the ambiguity, not a service.

  STK now delegates to `_resolve_stock_conid`, the resolver `get_market_snapshot` and `get_contract_info` already use, so there is **one** definition of "which listing did they mean" in this package instead of two that can drift. Three outcomes, none a guess: exactly one US listing (or one matching an explicit `exchange`) returns `{conid, currency, exchange}`; several or none returns the resolver's question naming every candidate **with no conid in it to lift**; IND/BOND keep the raw passthrough, because `/trsrv/stocks` is stocks-only and pretending otherwise would be a guess. A new `exchange` input answers the tool's own question — `IGV` resolves to 12658199/USD, `IGV` + `MEXI` to 325209548/**MXN**, both live-verified, and the currency is carried by `_Resolved` so it cannot be dropped on the way out.

  **The description was also wrong about the payload**: it advertised `exchange` and `currency`, and `/iserver/secdef/search` returns neither — no currency field at all, the exchange only as `description` and inside `sections`. Currency is precisely what separates a US listing from its foreign twin, so a caller trusting that promise read `None` at the worst possible moment. `client.search_contract`'s docstring claimed the same two keys and is corrected.

  **One defect found by running it rather than testing it**, and worth keeping even though the code it applied to is gone: an earlier build required an `isUS` verdict for every returned row and so did nothing at all for **AAPL and VOD** (4 of 5 rows covered for both). The uncovered row is conid **2147483647** (INT_MAX) — a *"Corporate Fixed Income"* aggregate with a null symbol and a BOND-only section, documented under bonds, which `/trsrv/stocks` rightly does not know because it is not a stock. IGV has no such row, which is why the first live check looked like a pass. Delegation removes the whole class: `/iserver/secdef/search` is no longer consulted for STK.

  845 tests, both design guarantees mutation-verified (resolving the ambiguous case instead of asking, and dropping the currency, each fail their intended test). Sources: [security-stocks-by-symbol](https://ibkrcampus.com/docs/web-api/v1/endpoints/contract/security-stocks-by-symbol.md) (`isUS` — *"States whether the contract is hosted in the United States or not"*), [search-contract-by-symbol](https://ibkrcampus.com/docs/web-api/v1/endpoints/contract/search-contract-by-symbol.md) (no currency field; ordering undocumented). Both read 2026-08-05.

- **The web scraper is now four tools with one job each and no fallback between them** (2026-07-30). Anything that takes a URL goes to the free local browser; Firecrawl keeps only whole-web search, the one thing the browser cannot do. `firecrawl_search` finds pages anywhere, `search_site` finds pages on one site, `crawl_site` archives a site to Drive, `fetch_page` reads one page. The first two return URLs; the last two return text.

  **The two-rung ladder was deleted because its premise was backwards.** It ran the paid engine first and fell back to the free one. Measured on the same URLs minutes apart: local returned 17,364 B in 1.2 s where Firecrawl returned 14,341 B in 16.8 s, and 8,786 B in 1.3 s against 5,515 B in 13.2 s — bigger, ~10× faster, free. Roughly 900 lines of arbitration went with it (`_merge_pages`, `_assess_fallback_need`, `_finalize_fallback_result`, `_scrape_with_fallback`, `_apply_crawl4ai_fallback_batch`, `_crawl4ai_root_scrape`, `_handle_firecrawl_crawl`), plus 330 lines of Firecrawl crawl machinery — job start, the 5 s polling loop, `next` pagination and its three termination guards. Net across the refactor: ~1,100 insertions against ~2,000 deletions.

  **The scraper no longer calls the Anthropic API at all.** `judge_completeness_llm` was the single documented exception to "ClaudeToolkit is the only layer that talks to Anthropic", and invisible to a host app's own token accounting. It is not better-guarded; with one engine per job there is nothing for a model to arbitrate.

  `WebDocsStore` is untouched — all 303 lines, the same `web_docs/` Drive layout, the same 48h manifest cache, the same slug-collision handling. It never referenced `FirecrawlClient` in code, only in docstrings, which is what let `crawl_site` slot in beneath it as a drop-in rather than a migration.

- **`firecrawl_search` finds without reading.** It used to fan out up to five concurrent local browsers to re-fetch every result, because Firecrawl's extraction was the only thing between the model and the page. It now returns URLs, titles and a ~400-character snippet, and points at `fetch_page`. Removing the extraction step is also what makes the search/read split legible to the model.

### Added
- **`search_site` — BM25-ranked page discovery within one domain.** Free: Crawl4AI's `AsyncUrlSeeder` over public sitemaps and the Common Crawl index, scored against each page's extracted `<head>`. ~5 s for 87 URLs. Two findings only a live run produced, both now load-bearing. **`extract_head=True` is mandatory, not a default** — with it 87 of 87 URLs are scored; without it *zero* are and the list is sitemap order. The vendor's own documented example omits the flag, so copying it yields something that looks like ranked search and is not. **A non-matching query scores 0.5, not 0.0** — the first live run answered "zzzq nonexistent topic xyzzy" with ten confidently-ranked pages (Privacy Policy, Contributing Guide, home page), every one at exactly 0.500, because BM25 gives every page a neutral score when no term overlaps. The unit tests had mocked a miss as 0.0: a mock weaker than its dependency, the same failure mode that let `create_profile` ship having never run. "Nothing matched" is now detected as a completely flat distribution, which the vendor's own `score_threshold` cannot express (0.51 empties the nonsense query but also discards genuine 0.400 hits).
- **`crawl_site` — archive a site with the local browser.** Breadth-first, same-host only (`include_external=False`, a safety property: it stops a hostile page walking the crawler onto another host), into the existing `WebDocsStore`. Works on sites behind a login, which the paid rung could not do at all. Two more live-only findings: **the strategy returns the root URL twice**, depth 0 and depth 1 byte-identical, which would make `save_crawl` write one file but record two manifest entries — found by probing the real API before writing the function. And **an error page is still a page**: crawling `docs.crawl4ai.com/core/` returned one 44-byte nginx `403 Forbidden` (that path is a directory prefix) and the handler reported "Crawl complete: saved 1 page(s)" while filing it into the research archive. That is the third instance of this trap here, after "saved 0 page(s)" reported as success and `fetch_page`'s "(1 B)" reading like a short page. It now refuses to save when every page grades `fallback`, and quotes the offending text.
- **`fetch_page` — a single-URL browser fetch tool** (44 tools total, 46 via the MCP server). Until now the only way to read one known URL was `firecrawl_crawl` against it, which archives up to 50 pages to Drive to answer a question about one — and which cannot open a paywall at all, because Crawl4AI was reachable only as a fallback *underneath* a Firecrawl attempt. `fetch_page` goes straight to the local browser: it finds a saved login profile by domain, states in its reply whether one was used, and returns the full article instead of the subscription stub. This is the piece that makes the paywalled-site capability (`docs/web-scraper-reference.md` §6) actually reachable; everything else — profile lookup, paywall detection, the `create-profile` CLI — was already built and tested. SSRF-validated before the browser is constructed, and degrades to a message (not a traceback) when the `[scraper]` extra is absent, the browser crashes, or the page comes back empty.

### Removed
- **The Crawl4AI Cloud rung** (`crawl4ai_cloud.py`, 432 lines, 37 tests, added earlier the same day). The recovery ladder is two rungs again: Firecrawl → local Crawl4AI. It bought nothing the local browser did not already do — on the only real block ever observed (2026-07-02, IBKR/Akamai) the free local rung won with 144,125 chars, so the paid rung addressed a failure mode never once seen. It also could not serve the requirement that motivated Crawl4AI in the first place: opening a paywall through Cloud would mean uploading a logged-in WSJ/FT session to a third party, and the vendor's own SDK does not even wrap that endpoint. `Config.crawl4ai_api_key`/`crawl4ai_api_url` and the `crawl4ai-cloud-sdk` dependency go with it; `Config.crawl4ai_profiles_dir` (the near-identically-named *paywall* setting) is unaffected. Findings from the live API — four vendor-doc errors and a response field that misreports its own billing — are preserved in `docs/web-scraper-reference.md` §5.1 as evidence for the standing "a published reference is a claim, not evidence" rule.

### Fixed
- **The crawl ladder's root rescue discarded Firecrawl's pages instead of adding to them.** `_handle_firecrawl_crawl` did `pages = root_pages` whenever the local rung's single root page outweighed everything Firecrawl returned. That honored the documented promise ("a fallback can never shrink what Firecrawl already returned") bytewise while breaking it page-wise: three genuinely complete ~1.5 KB documentation pages measure under the 5 KB bar, so a larger root scrape archived one page to Drive and silently dropped the other three. The rescue now merges by URL (`_merge_pages`), larger markdown winning when both rungs return the same URL, so it can only ever add. Because merging cannot cost anything, the rung no longer has to win outright to be used, and the `Source:` line names both rungs when both contributed. Regression tests: `test_root_rescue_keeps_firecrawls_pages_instead_of_replacing_them`, `test_root_rescue_prefers_the_larger_markdown_for_a_duplicated_url`, `test_local_rung_does_not_replace_a_larger_firecrawl_result`.
- **`fetch_page`'s tool description promised the model something false.** It named WSJ among the paywalled sites that "return the full article instead of the subscription stub". Re-measured 2026-07-30 with a real saved WSJ profile in place: `wsj.com` returns 1 B at HTTP 401 ("Blocked by anti-bot protection: DataDome captcha") headless *or* visible, with the profile *or* without — the block precedes authentication, so no login can move it. The description now says a saved profile is needed, names `wsj.com` as confirmed-blocked, and tells the model to report the block rather than retry or claim the page was read. `docs/web-scraper-reference.md` §6 carries the full status, and `ft.com` (59,455 B, HTTP 200, no profile) is identified as the host to prove the paywall path on.
- `FirecrawlClient.search()`/`.crawl()` were annotated `-> list[dict[str, str]]`, but both methods' own docstrings already documented a `"metadata": dict` field returned alongside the `str` fields — the annotation didn't match the method's own contract. Widened to `list[dict[str, Any]]` (4 sites in `web_scraper.py`); no behavior change, Python never enforced the narrower type at runtime. Found during the 2026-07-22 code-quality audit — see `docs/audits/2026-07-22-code-quality-audit.md`.
- `get_account_summary` no longer claims `/portfolio/{accountId}/summary` carries P&L fields — that endpoint's ~90-key response never includes `unrealizedpnl`/`realizedpnl` (live-verified 2026-07-17, confirmed against official docs); the tool description and formatter now point to `get_ledger`/`get_pnl` instead. See `docs/plans/2026-07-17-account-pnl-display-fixes.md` in the sibling `claudia_ui` repo.
- `get_pnl` (`/iserver/account/pnl/partitioned`) returned an empty `{"upnl": {}}` on a cold gateway session — even with open positions and real P&L — until something subscribed to the `spl` WebSocket topic at least once (live-verified 2026-07-17; same undocumented warm-up class as `/iserver/marketdata/snapshot`). `_get_pnl` now self-primes: on an empty first response it does a best-effort `spl` subscribe/unsubscribe touch and retries once, never raising on failure.
- Backtest sandbox strategy code that timed out (e.g. `while True: pass`) survived the 10-second timeout indefinitely in an orphaned `ThreadPoolExecutor` thread — `Future.cancel()` cannot stop a thread already executing. Worse, `concurrent.futures.thread` registers a non-daemon-thread join in its interpreter-shutdown hook, so a host process that ever hit this path could hang indefinitely on exit. The sandbox now runs strategy code in an isolated `multiprocessing.Process`, with a daemon watchdog thread that force-kills the child (SIGTERM, then SIGKILL after a grace period) if the timeout elapses — a real OS process can be forcibly stopped, unlike a thread. `run_backtest()`'s public signature and exception contract are unchanged. Full mechanism, including why `concurrent.futures.thread`'s shutdown hook could hang the host and why killing the child is what unblocks the parent's pipe read: `docs/plans/archive/infrastructure/2026-07-15-backtest-sandbox-subprocess-isolation-design.md`.

### Changed
- `[tool.mypy]` now sets `files = ["ibkr_core_mcp", "tests"]` — `tests/` (39 modules, 747 tests) had never actually been type-checked by CI or locally, only `ibkr_core_mcp/` was. A narrow `tests.*` override relaxes `disallow_untyped_defs`/`disallow_incomplete_defs`/`disallow_untyped_calls` (this codebase's tests have zero signature annotations by established convention) while every other `strict` check, including body-level `check_untyped_defs`, stays on. Surfaced 183 real findings across 12 test files, all fixed; CI's `mypy` step updated to match. Full inventory and triage: `docs/audits/2026-07-22-code-quality-audit.md`.

---

## [1.2.2] — 2026-07-15

### Fixed
- Dev `.venv` was accidentally built on Python 3.14 (Homebrew never had 3.11 installed on this machine) — reverted to 3.11; `requires-python` now pins `>=3.11,<3.14` and rejects 3.14 interpreters at install time, matching the `3.11`–`3.13` classifiers already declared. No 3.14-specific code existed in the package itself; this is a guardrail against future silent drift, not a functional-incompatibility fix.
- `websockets` moved from the `[server]` optional extra into base `dependencies` — `IBKRWebSocket`/`AlertManager` are exported from the package's top-level `__init__.py` as core public API, not server-only functionality, but their sole dependency was gated behind an extra alongside `mcp`/`starlette`/`uvicorn` (which remain server-only — they're used exclusively by the standalone `mcp_server.py` entry point). Consumers that `import IBKRWebSocket` directly without running the MCP server previously got a silent `ModuleNotFoundError` at runtime instead of an install-time failure.

---

## [1.2.1] — 2026-07-14

### Fixed
- `docs/api-usage-examples.md`: two print statements used `:.1f}%` instead of `:.1%` for `max_drawdown` (a negative fraction), which would silently print a 30% drawdown as "-0.3%"; the Portfolio Analytics 1-minute-bar example passed `periods=1440` (minutes/day) instead of `98280` (bars/year), mis-annualizing Sharpe/Sortino/CAGR/Calmar by ~68x

---

## [1.2.0] — 2026-07-14

### Added
- Firecrawl requests now retry on 429/408/5xx with Retry-After-aware exponential backoff (search, crawl job-start, crawl polling)
- `firecrawl_crawl` checks a Drive read-cache (<48h) before re-fetching a previously-archived URL

### Fixed
- `get_pa_transactions` was sending IBKR the wrong request body (a period string instead of a resolved conid) — redesigned to take `symbol`/`sec_type`/`currency`/`days`, matching `client.py`'s real signature
- `FirecrawlClient.crawl()` now follows the `"next"` pagination cursor — crawls whose result exceeded 10MB were silently truncated to the first chunk; retry loop bounded
- `_scrape_with_fallback`'s "Crawl4AI fallback used" reporting no longer overcounts — it now returns an explicit `used_fallback` flag instead of inferring from a non-empty note; `WebDocsStore.save_crawl` disambiguates filenames that collide after slugifying (e.g. `/a-b` vs `/a_b`)
- `gdrive_auth.load_or_refresh_credentials()` docstring promises it never raises, but an uncaught `RefreshError` from a revoked/expired token could propagate anyway — now caught and treated as no-credentials, matching the documented contract
- `pyproject.toml`'s `version` field was never bumped for the `v1.1.0` tag (stayed at `1.0.0`) — since `__version__` is derived via `importlib.metadata`, any `v1.1.0` install silently self-reported `1.0.0`. Corrected to `1.2.0` here; that stale `v1.1.0` tag itself is left as-is rather than rewritten.

---

## [1.1.0] — 2026-07-12

### Added
- Crawl4AI fallback (`local_browser.py`) for incomplete/paywalled Firecrawl results, gated by an LLM completeness check
- WebSocket `str` (trades) and `spl` (P&L) topics added to `IBKRWebSocket`
- `IBKRClient.place_order_and_confirm()` / `modify_order_and_confirm()` — loop Gate 1 (Touch ID) + Gate 2 (dialog showing the real IBKR reply text) across a chained-reply sequence until a terminal order state is reached
- `cancel_order()` gained an optional `order_details` param so Gate 2's cancel dialog shows full order details instead of just the order ID
- Futures support (STK/FUT/FOP) added to order staging
- `client.get_orders_raw()` / `get_pa_periods_raw()` made public — removes the last private `client._get`/`client._post` reach-ins from `claude_tools.py`
- `get_option_chain` reimplemented via the documented `secdef/search` → `secdef/strikes` flow

### Fixed
- SSRF guard closes DNS-rebinding and open-redirect gaps in the Crawl4AI fallback path
- `preview_order` gains `stop_price`/`sec_type` schema fields with correct `price`/`auxPrice` mapping for STP/STOP_LIMIT orders (previously a live HTTP 500 for any stop order)
- `get_option_strikes` read a nonexistent `'strike'` key and claimed the wrong month format (`'JAN2026'` vs IBKR's actual `'JAN26'`)
- `get_pnl` response shape corrected to match IBKR's documented `/iserver/account/pnl/partitioned` format; `create_price_alert`'s advertised FUT/OPT/FX support was unreachable and now resolves through the same conid-resolution path as market data
- `get_live_orders`/`diagnose_orders` checked `orderRef`/`cOID` instead of IBKR's real `order_ref` field — every order, including ClaudIA's own, fell through to an unreliable `clientId` check and was mislabeled EXTERNAL
- Chained order-reply confirmations (e.g. price-band %, no-market-data, mandatory-cap-price warnings) now auto-resolve through Gate 1 + Gate 2 instead of requiring manual `reply_order()` calls per step; the reply dialog shows the real IBKR warning text (HTML-stripped) instead of just a reply ID
- `run_backtest` sandbox errors now surface the real exception type and message (plus available DataFrame columns and the `signal` contract) instead of a redacted "strategy runtime error" — the LLM can no longer self-correct from a blanked message
- `get_analytics` annualizes by the request's actual timeframe instead of always assuming daily bars
- Flex `_get_statement` no longer swallows a `Warn`/error-1019 response as if it were a valid (empty) statement
- `get_market_history` period/bar values are lowercased before the request — IBKR silently mis-serves uppercase periods (e.g. `'6M'` returned ~4 months of data, not 6) and the tool schema itself had been teaching the LLM the wrong case
- `get_trades()` auto-retries an empty first response once — `/iserver/account/trades` has the same two-call subscription warmup as `/iserver/account/orders`; a prior "mobile fills missing" observation was this warmup, not an origin filter
- False "DATA STALE" warning on Flex sync no longer fires on ordinary T+1 lag (newest trade == yesterday); threshold now requires 2+ trading days with no new data
- `_create_alert` correctly detects a 403 response returned as toolkit text (the internal `except IBKRAPIError` branch never fired, since `ClaudeToolkit.execute()` already converts it to text)
- Gate 1 Touch ID policy corrected in-code and in docs to `LAPolicyDeviceOwnerAuthentication` (biometric with system-password fallback, not biometric-only)

### Security
- 5 GitHub CodeQL alerts resolved: least-privilege `permissions: contents: read` added to the CI test job; 3 `py/incomplete-url-substring-sanitization` false positives replaced with structural checks or suppressed with justification
- `DataFrame.eval`/`.query` blocked in the backtest sandbox — both run pandas' own expression engine outside `RestrictedPython`'s AST guards and could reach `sys.modules['os']` for RCE
- `order_id`/`alert_id`/`reply_id` now validated against strict regexes before URL construction — `delete_alert(alert_id="../order/<id>")` previously normalized to `cancel_order`'s exact URL, bypassing Touch ID and the confirmation dialog on live order cancellation
- `_ORDER_ID_RE` tightened from Unicode `\d` (accepted non-ASCII digit code points) to an explicit `[0-9]` class
- Gateway Docker container now binds to `127.0.0.1` explicitly — the prior `-p {port}:{port}` form published on all host interfaces by Docker's default behavior, not loopback-only as documented
- Gateway `conf.yaml` IP allowlist scoped from `192.*`/`172.*` (which matched the full `/8` blocks, including public IPv4 space) to the actual RFC 1918 ranges
- SSRF guard (`scrape_fallback.is_private_host`) now resolves both A and AAAA records via `getaddrinfo` — an IPv6-only private host previously bypassed the guard entirely via `gethostbyname`'s IPv4-only resolution
- `import_flex_file`'s path-boundary check switched from `str.startswith()` to `Path.is_relative_to()` — a sibling directory whose name was a superstring of `.ibkr_core` (e.g. `.ibkr_core_evil`) previously passed the allowlist

### Changed
- `analytics.sortino` migrated to the canonical target-downside-deviation form (Sortino's own definition, computed over all observations, not just below-target ones) — pre-migration Sortino figures are not directly comparable to figures produced after this change
- `claude_tools.py` full audit (design decisions D1–D5): several tool descriptions and behaviors corrected across the 42-tool set

---

## [1.0.0] — 2026-06-27

### Fixed
- `analytics.full_report()` hardcoded `periods=252` — now accepts `periods: int = 252` kwarg; intraday callers now get correct annualised Sharpe/Sortino/Calmar/CAGR
- `ClaudeToolkit.execute()` return type corrected to `tuple[str, None]` — was documented as returning an optional plotly figure but always returned `None`; second element reserved for future figure support
- mypy: 14 type errors resolved across 5 files (see below)
  - Missing `Path` import in `cache.py`
  - Missing `log` logger in `flex_query.py`
  - Bare `dict` / `list[dict]` annotations upgraded to fully typed equivalents
  - `conid` passed as `str` where `int` expected in two `ClaudeToolkit` handlers
  - Untyped lambda replaced with typed `def _has_prices(...)` in market snapshot handler
  - `Credentials.from_authorized_user_file` suppressed with `# type: ignore[no-untyped-call]` (third-party stub gap)
  - `save_crawl` return type narrowed; Drive file IDs wrapped in `str()`
- `__version__` now derived from `importlib.metadata` — single source of truth is `pyproject.toml`; eliminates drift between `__init__.py` and `pyproject.toml`

### Added
- Firecrawl web scraper integration: `firecrawl_search` and `firecrawl_crawl` Claude tools, `FirecrawlClient`, `WebDocsStore` with Drive persistence
- `SQLiteStore.get_market_calendar_context()` — NYSE + CME trading calendar for LLM context-aware scheduling
- `get_market_calendar_context`, `FirecrawlError`, `WebDocsStoreError` exported from `__init__.py`
- SSRF guard on `firecrawl_crawl` — only `https://` URLs with public hostnames accepted
- 484 unit tests (46 new ClaudeToolkit handler tests, 13 GDriveCache Drive path tests)
- Source: URLs on all IBKR Client Portal API docstrings
- `Field(description=...)` on all aliased Pydantic model fields — IDE autocomplete and `model.model_fields` expose IBKR wire-format field names
- `AuthStrategy` Protocol exported from `ibkr_core_mcp.__init__`
- `py.typed` registered in `[tool.setuptools.package-data]`
- Complete IBKR Flex error code table (21 official codes) in `flex_query.py`
- Docstrings with official IBKR CP API source citations on all 76 `IBKRClient` public methods
- Optional `start_date` / `end_date` parameters added to `FlexQueryClient.fetch_trades()`

### Changed
- `plotly` removed from package dependencies — was never used
- Dead HMDS code removed from `client.py`
- `_BROWSER_LOADERS` dict removed from `auth.py` — was mapping each name to itself

### Security
- `store._apply_filters` `time_col` parameter validated against allowlist before SQL interpolation
- Silent exception swallowing replaced with `log.warning(...)` in `flex_query.py` and `claude_tools._run_backtest`
- `WebDocsStore._get_service()` token file written with `0o600` permissions

---

## [Unreleased — earlier]

### Added
- `py.typed` registered in `[tool.setuptools.package-data]`
- Docs-first principle established: all external API behavior must be verified against official documentation before implementation; reference URLs added to `CLAUDE.md`, `README.md`, and inline comments
- Complete IBKR Flex error code table (21 official codes) in `flex_query.py`, sourced from https://www.ibkrguides.com/clientportal/performanceandstatements/flex3error.htm
- `with_retry()` docstring cites official IBKR rate limit policy and documents Retry-After behavior
- Optional `start_date` / `end_date` parameters (`fd` / `td`) added to `FlexQueryClient.fetch_trades()` for date-range overrides
- `_validate_flex_date()` helper in `flex_query.py` enforces YYYYMMDD format

### Fixed
- `ping()` try/except split so `tickle()` errors are no longer silently swallowed
- Drive `market_data/` folder discovery now sorts by `createdTime asc`; warns when duplicates exist
- Account ID regex unified: both `client.py` and `claude_tools.py` now enforce `^[A-Z0-9]{4,12}$`
- `py.typed` moved into `ibkr_core_mcp/` package directory (was at repo root — invisible to pip consumers)
- OS classifiers expanded: Linux and Windows added alongside macOS
- README: `--streaming` flag corrected to `--stream`, git+ install form, model ID updated
- **Flex Web Service endpoint** corrected from `gdcdyn.interactivebrokers.com` to `ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/` — wrong from day one
- **Required `User-Agent: Python/3` header** added to all Flex requests
- **Flex error 1001** correctly documented as transient generation failure (not rate limit)

---

## [0.4.0] — 2026-06-10

### Added
- **MCP server** (`ibkr_core_mcp.mcp_server`): 33 tools + 2 MCP-only alert tools + 3 resources; supports stdio and HTTP/SSE transports
- `--stream` flag for MCP server: enables WebSocket live quotes and price alert delivery
- **Streaming** (`streaming.py`): `IBKRWebSocket`, `LiveQuote` dataclass, `AlertManager`
- Price alerts persisted to SQLite (`price_alerts` table); `add_price_alert` / `get_price_alerts` MCP tools
- `sync_flex_trades` Claude tool for pulling full historical trade history via Flex Query
- `FlexQueryClient` hardens datetime parsing, URL validation, and type annotations
- Drive layout: `market_data/` subfolder auto-created inside `GOOGLE_DRIVE_FOLDER_ID`; `db/` subfolder for claudia.db
- `IBKRWebSocket` localhost guard — refuses non-localhost URLs at connect time
- 170 unit tests passing

### Security
- Full security audit (2026-05-25): all Critical/High/Medium findings resolved
- `SECURITY.md` added with responsible disclosure policy and threat model

---

## [0.3.0] — 2026-05-28

### Added
- **Touch ID gate** (`human_auth.py`): `require_touch_id()` via `pyobjc-framework-LocalAuthentication`; fingerprint-only, no password fallback, 60 s timeout
- **Confirmation dialogs** (`order_confirm.py`): tkinter modal for place/modify/cancel/reply; mouse click required, Enter key does not confirm
- Two-gate enforcement on all order write methods: `place_order`, `modify_order`, `cancel_order`, `reply_order`
- `HumanAuthError` exception exported from public surface
- Read-only endpoints explicitly ungated: `get_order_preview`, `get_live_orders`, `get_order_status`, alert endpoints

### Security
- Order write path requires fingerprint + visual confirmation before any IBKR network call
- `CLAUDE.md` security section documents two-gate architecture and contributor rules

---

## [0.2.0] — 2026-05-22

### Added
- **Technical indicators** (`indicators.py`): 14 pure-function indicators — SMA, EMA, RSI, MACD, Bollinger Bands, ATR, Stochastic, Williams %R, Keltner Channels, VWAP, OBV, Volume SMA, Volume Ratio; `add_all()` convenience
- **Portfolio analytics** (`analytics.py`): Sharpe, Sortino, Calmar, CAGR, max drawdown, max drawdown duration, win rate, profit factor, avg win/loss ratio, `full_report()`
- **Backtesting sandbox** (`backtest.py`): `RestrictedPython` executor; no network, no file I/O, no `os` access; `BacktestResult` dataclass
- **PineScript generation** (`pinescript.py`): v5 strategy and indicator scripts from backtest results or signal series; injection-safe `_sanitize()` helper
- **Pydantic v2 models** (`models.py`): `Contract`, `Position`, `Trade`, `Order`, `AccountSummary`, `Notification`; `bars_to_dataframe()` OHLCV normalizer
- `ClaudeToolkit` expanded to 19 tools including `add_indicators`, `run_backtest`, `generate_pinescript`, `get_analytics`
- `FlexQueryClient` for full historical trade data via IBKR Flex Web Service (6-day API limit bypass)

---

## [0.1.0] — 2026-05-15

### Added
- **`IBKRClient`** with all 79 IBKR Client Portal API endpoints
- **`GDriveCache`**: Google Drive parquet cache for OHLCV market data; manifest with TTL
- **`SQLiteStore`**: trades, position snapshots, signals, backtest results, log entries
- **`ClaudeToolkit`**: 15 Claude tool definitions + handlers (read-only, no order execution)
- **`GatewayManager`**: Docker lifecycle management for IBKR Client Portal Gateway
- **`Config`**: dataclass loaded from environment variables; `from_env()` factory
- Auth strategies: `BrowserCookieAuth` (Chrome cookie), `TokenAuth`, `NoAuth`
- Custom exception hierarchy: `IBKRCoreError` → 12 typed subclasses
- Token-bucket rate limiter + exponential backoff on 429 (`rate_limiter.py`)
- `py.typed` marker (PEP 561)
- Full unit test suite (no gateway required for unit tests)

---

[Unreleased]: https://github.com/stephus182/ibkr_core_mcp/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/stephus182/ibkr_core_mcp/compare/v1.2.2...v2.0.0
[1.2.2]: https://github.com/stephus182/ibkr_core_mcp/compare/v1.2.1...v1.2.2
[1.2.1]: https://github.com/stephus182/ibkr_core_mcp/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/stephus182/ibkr_core_mcp/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/stephus182/ibkr_core_mcp/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/stephus182/ibkr_core_mcp/compare/v0.4.0...v1.0.0
[0.4.0]: https://github.com/stephus182/ibkr_core_mcp/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/stephus182/ibkr_core_mcp/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/stephus182/ibkr_core_mcp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/stephus182/ibkr_core_mcp/releases/tag/v0.1.0
