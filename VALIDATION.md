# Validation record

Updated locally on 2026-10-24 (Asia/Shanghai) in the existing project at `/Users/macbook1/Documents/Job/Fric Law/FRIC_LAW_Content_Studio`.

## AI Box recheck and contextual repair guidance on 2026-10-24

The user supplied a fresh screenshot showing the configured Flash model's HTTP 503/channel failure and confirmed that AI Box had not yet been contacted. The local app was healthy. No endpoint, API key, model or Codex/ChatGPT setting was changed.

- Authenticated `GET /v1/models` returned **200**, listing `deepseek-v4.1-flash` and `deepseek-v4-pro-0813`.
- One minimal generic generation probe for each listed model returned **503**, classified as `model_unavailable`. Latest Flash request ID: `202610240613239989039318268d9d6GXGHkD9h`; Pro request ID: `202610240615166594966528268d9d6Wv7xrnLV`. No article/client data was sent. Neither listed model was confirmed working; the saved Flash selection was preserved.
- Read-only code review found no client defect explaining this response: routing/authentication/request format matched the configured AI Box integration. An account/model channel remains the external blocker. The previous raw response naming `Vip (distributor)` is historical evidence from 23 October, not a newly exposed account field in this turn.

The UI now shows channel/group-specific next steps and a direct API Keys management link for this error, rather than asking an already configured user to create another key. A copyable support report contains only endpoint, model, HTTP status, normalized application code and request ID; the whole report is redacted against known credentials and excludes provider message bodies/source/draft text. The app does not send it to anyone. Success/failure results record an explicit response time in Asia/Ho_Chi_Minh; rerendering retains that timestamp and is not a new API check. Older session state without a timestamp is handled explicitly. Draft/manual review/export requirements remain intact.

Validation:

- **245 tests passed**, no failures or skips, in **24.236 seconds**, including **20 editorial smoke tests**. The three new regressions cover contextual instructions, support-report redaction/exclusion, and timestamp persistence/legacy-state compatibility without render-time API calls.
- Ruff lint, Ruff format check (**36 Python files**) and compileall for the changed application/tests passed. No dependency changes were made.
- Fresh real Chrome loaded local `http://127.0.0.1:8501/`, opened the writer and AI connection panel, recognized the configured key with a blank password field, hid create-key onboarding, and showed the fresh browser session as unchecked. No provider probe was clicked in browser QA; no page exceptions occurred.
- The real server was not restarted, avoiding deliberate loss of the user's active in-memory draft. Source code and updated support instructions were saved in place. No human/provider account operation, support message, real draft save, approval or export was performed.

AI generation is **still not operational with the current key**. AI Box/the account owner needs to enable a working permitted channel/group/model or provide another valid configuration through the local password UI. Application tests and a successful model-list request do not establish live generation success.

Earlier records follow for history.

## Repeated Quick Tunnel 1033 checked on 2026-10-23

The user's screenshot shows Cloudflare 1033 at **15:04:16 UTC / 23:04:16 Asia/Shanghai**. Connector logs show loss at **15:03:41 UTC**, then successful registration at **15:04:22 UTC** on the same URL. Both local 8501 and authenticated backend 8502 remained healthy. Further connector losses/reconnections were observed while investigating. This evidence establishes intermittent tunnel connectivity; it does not isolate the VPN, sleep, ISP or Cloudflare as the definitive cause. The earlier successful check was only a point-in-time result.

Implemented:

- `start/status` now check the exact recorded public HTTPS route at `/_stcore/health`, requiring HTTP 200 and body `ok`, in addition to the owned connector and backend. Requests are bounded, verify TLS, do not follow redirects or send credentials, and never echo upstream bodies.
- New `run_share.py recover` keeps the existing live connector PID, URL and login files, waits for reconnection with a bounded deadline and restarts only the application's unhealthy backend with authentication enforced. It refuses unrelated occupied ports, missing login files and dead/unverified connectors. It does not silently rotate a URL or create replacement credentials.
- A temporary public-route failure after provisioning leaves the saved connector/state intact for recovery. A fresh new tunnel reloads only an owned old backend so its public hostname/auth environment is current.
- [HUONG_DAN_DEPLOY_24_7.md](HUONG_DAN_DEPLOY_24_7.md) gives beginner GitHub-private-repository/Render instructions. A **48-file clean source folder** was prepared at `/Users/macbook1/Documents/FRIC_LAW_Deploy_Source`, with SHA-256 manifest. The exact selected contents were checked against configured API secrets and the team password without printing them. No `.env`, runtime files, database, MASTER, client documents or OAuth credential/token was copied.

Validation:

- **242 tests passed**, no failures or skips, in **20.750 seconds**, including **24 sharing tests** (13 new cases). These cover public HTTP/body/redirect failures, recovery without process/URL/password changes, refused unrelated ports and a new hostname's backend reload. Tests do not signal real processes or contact real providers.
- Ruff lint/format (**36 Python files**), compileall, `pip check` and macOS command syntax checks passed.
- Actual `recover` returned success while retaining **`https://jets-respond-sbjct-bunny.trycloudflare.com`**, its connector and credentials. Direct external checks observed HTTP 200 for the root Streamlit shell and `/_stcore/health`. These checks do not establish continuous availability or complete frontend loading.
- Local real Chrome loaded the navigation with zero asset failures/console errors. External Chrome reached HTTP-200 login and authentication, but subsequent widgets intermittently remained loading; the final public browser smoke check **did not pass**. The public route is not being reported as reliably repaired. No AI probe, real source/draft/export or account change was made in this turn.
- No Docker engine/build, live Render service, account or paid resource was created. The hosting guide was checked against current official Render Blueprint/disk docs and GitHub docs; actual deployment still needs the user's GitHub/Render account, billing decision, image build, disk permissions and end-to-end HTTPS/WebSocket/data-persistence checks. AI Box group/channel repair remains independent.

References: [Cloudflare 1033](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/troubleshoot-tunnels/common-errors/#i-see-an-error-1033-when-attempting-to-run-a-tunnel), [Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/), [Render Blueprint](https://render.com/docs/blueprint-spec), [persistent disks](https://render.com/docs/disks).

Earlier records below are historical snapshots, including temporary-link successes; they are not current uptime guarantees.

## AI Box channel diagnosis and writer failure handling checked on 2026-10-23

The previously reported generic service failure was investigated through minimal generic requests, without article/client data. AI Box returned **HTTP 503**, `error.code=model_not_found`, `error.type=new_api_error`, with a message that `deepseek-v4.1-flash` has no available channel in the key's **Vip (distributor)** group. Streaming Chat Completions and the documented `/v1/messages` endpoint returned the same group/model error. The documented `ds/deepseek-flash` alias returned **403**, denying the token access. Reading `/v1/models` successfully does not prove that generation has an active channel. No working permitted generation route was established, and no model/format fallback is enabled.

Implemented in the existing app:

- The adapter identifies structured channel/model failures before generic 5xx handling, emits actionable predefined Vietnamese text, and retains only a validated HTTP status and opaque request ID. Keys, source text and raw provider error messages remain excluded; network/permission/quota errors retain their own classifications. Requests stay at AI Box, with no automatic retry or provider/model switch.
- A failed generation clears a stale green connection result and preserves the title, body, sources, notes and confirmation state. The failure panel is bound to the exact configuration revision and remains visible across rerenders; reopening the page does not call the provider. The local setup CLI also displays safe HTTP/request-ID diagnostics.
- Manual drafting, evidence review, editor/lawyer sign-off and append-once Word export remain independent of AI availability and retain their approval requirements. A new end-to-end UI regression exercises this workflow while the AI failure remains present.
- [AI_BOX_KIEM_TRA_KENH.md](AI_BOX_KIEM_TRA_KENH.md) explains the account-side repair and contains a support draft with safe request IDs. No support message was sent, no provider account/group was changed, and no Codex/ChatGPT configuration was modified.

Validation:

- **229 tests passed**, no failures or skips, in **20.314 seconds**. Includes 24 real-SDK/mock-HTTP adapter tests, 17 Streamlit editorial smoke tests and 15 setup CLI tests. Tests use isolated files/workspaces and do not make actual provider calls.
- Ruff lint and formatting (**35 Python files**), compilation of the application/deployment/tests, `pip check`, and syntax checks of the three macOS command files passed.
- Both app processes were explicitly refreshed to load all imported modules. Local ports 8501 and 8502 returned **200 / ok**.
- Real Chrome on local 8501 clicked the explicit connection probe and confirmed the new channel/model diagnosis, **HTTP 503** and validated request ID. The generic outage message and stale success state were absent; temporary title/body text survived and manual save remained available. No real draft was saved, no article source was sent and no key was visible. There were no browser exceptions or Streamlit exception panels.
- The prior Quick Tunnel was discovered to be invalid (`Unauthorized: Tunnel not found`), despite its connector process still existing. It was replaced using the existing authenticated launcher and credentials. The new temporary URL is **`https://jets-respond-sbjct-bunny.trycloudflare.com`**. Tunnel readiness and external **200 / ok** health checks passed, and real Chrome loaded the external page, logged in, opened the writer, preserved temporary title/body text, confirmed zero API-key mutation fields and no browser/Streamlit exceptions, then logged out. No additional provider probe was sent from the shared browser. The old external URL is no longer the current deployment. This remains dependent on the Mac being awake/online, with no 24/7 hosting claim.

Live AI drafting remains blocked by the account group's missing model channel. AI Box/the account owner must activate an allowed working channel/group or provide a different valid key/model through the local password UI, followed by a successful generation probe. This is distinct from the passing application regression tests. Human evidence/legal/editorial checking is still required for every article.

Earlier validation records follow for history.

## AI Box website-only integration checked on 2026-10-23

The user selected AI Box for the website and explicitly requested that this Codex conversation keep its existing ChatGPT authentication/quota. The pasted Codex CLI configuration is reference material; its instructions to change global Codex configuration were not executed.

Implemented:

- Website drafting exclusively uses `https://api.ai-box.vn/v1/chat/completions` with `AIBOX_API_KEY`/`AIBOX_MODEL`. No Responses API call, automatic provider fallback, custom destination URL or redirect to another host is accepted. The OpenAI Python SDK is only the client library.
- Website configuration ignores unrelated `OPENAI_API_KEY`, model/base URL settings and suppresses inherited OpenAI organization/project/custom headers per request. Saving website settings preserves unrelated variables/files. No real `~/.codex` authentication, model catalog or configuration file was modified.
- The local/private configuration UI, CLI and deployment templates now use AI Box labels and variables. The endpoint is read-only; shared editors cannot change keys/model. Existing draft preservation, evidence requirements and editor/lawyer approvals remain enforced.
- An AI Box key was available through the execution environment. It was saved only in the project's ignored `.env` with mode `0600`, together with `deepseek-v4.1-flash`. No key was printed, placed in documentation, passed through a shell argument or committed. Both existing app processes were refreshed without changing the external URL.
- Fixed Unix restart port detection to distinguish a stopped server's TIME_WAIT connections from an active listener. Added actual ephemeral socket regressions; owned-process checks and unrelated-process protection remain in place.

Final validation:

- **219 tests passed**, no failures or skips, in 17.407 seconds. Includes 17 real-SDK/mock-HTTP adapter tests, 15 editorial UI smoke tests, 14 settings tests, 14 setup CLI tests, 12 access tests and 10 launcher tests, plus all prior research/export/sync tests.
- Ruff lint, formatting (34 Python files), compileall, `pip check` and macOS shell syntax checks passed. Updated Compose/Render configs also passed their official schemas; no cloud resource or image build was performed.
- Adapter tests confirm every request stays at the AI Box endpoint with the AI Box bearer, even when unrelated OpenAI credentials/headers/base URL are present. A redirect to `api.openai.com` is rejected after one request. No test sends actual API traffic.
- Real Chrome verified local and authenticated external writer pages: AI Box endpoint shown; saved key recognized; local password field blank; no secret visible; no legacy OpenAI input; shared page has no key mutation field. Both pages had no browser exceptions/red error alerts. No real article source was submitted during browser validation.
- Local 8501, shared 8502 and tunnel readiness checks passed. External `/_stcore/health` returned **200 / ok**. External URL remains `https://cabinets-tel-welding-vcr.trycloudflare.com`.

Live provider checks, separate from the tests:

- Authenticated `GET /v1/models` returned **200**, listing `deepseek-v4.1-flash` and `deepseek-v4-pro-0813` for the available key. The guide's Qwen example was not in this list and its probe returned **403**; it was not used as the saved website model.
- Tiny generic Chat Completions probes for both listed models returned upstream service failures; `deepseek-v4-pro-0813` and a later Flash probe were confirmed **503**. A bounded larger diagnostic token allowance did not resolve the Flash 503. These requests contained only a generic connection-check instruction, no source/client data. No successful text generation is claimed.
- AI Box availability/account/model service status remains the external blocker for live drafting. The UI reports a safe provider error and keeps drafts; it does not route failures into the user's ChatGPT/Codex quota. No new API key is required merely to repeat the successful model-list check; generation requires the provider to accept the model request.

Earlier validation records follow for history.

## AI connection and drafting repair checked on 2026-10-23

The user confirmed they do not have an OpenAI API key. No local `.env`, OpenAI secret in the process environment or Streamlit secrets file was present. The original notice was therefore a real missing-credential state, not evidence of an API outage. No key was invented, copied from Codex authentication, requested in chat or stored during validation.

Implemented in the existing writer:

- Inline **Kết nối AI OpenAI** guide with official project/API-key/Billing links. On the local admin app, password input and model configuration save atomically with private permissions, clear password widgets, and apply without restarting. Shared editors cannot change keys/model; they can reread server configuration and explicitly test it.
- Stored configuration, unchecked configuration, a successful actual probe, and a failed probe have different states. A probe result belongs to the exact key/model fingerprint and is invalidated on change. Opening/rendering or saving configuration never calls OpenAI automatically. The explicit connection button sends only a small generic request and discloses possible API charges.
- `ai_client.py` uses the installed OpenAI Python SDK's Responses API, an explicit official endpoint, finite timeouts/output limits, `store=False`, no automatic retries, and proper resource closing. The existing model default is preserved. Temperature is omitted to avoid incompatibility with user-selected reasoning models. Error messages distinguish authentication, permission, model, billing/credit/spend/usage limits, rate limits, network/timeout and service failures without echoing provider messages, keys or source text.
- Generation keeps the existing source-text and official-source guards. Incomplete, refused or empty outputs are rejected. A failed generation/probe/save retains the current title/body/source selection; a completed draft is still unverified and needs independent claim review and both approvals before export.
- `setup_ai.py` and `connect_ai_mac.command` provide optional local setup using hidden input, no key arguments and safe cancellation. A terminal unable to hide input is rejected before key entry. Startup `.env` loading reads only workspace plus API settings; a config file cannot disable hosted authentication. Docker source allowlists include the new AI adapter and exclude keys/runtime data.

Validation:

- **207 tests passed**, no failures or skips, in the final full run (17.826 seconds). Includes 14 AI adapter tests using the real SDK over a mocked HTTP transport, 14 editorial Streamlit smoke tests, 10 settings tests and 12 local setup CLI tests, plus all previous research/approval/export/hosting tests.
- Ruff lint and formatting passed for all 34 Python files. Compileall, `pip check`, and syntax checks for the three macOS command files passed.
- A mocked completed Responses request exercised `core.generate_article` through the SDK and populated the actual Streamlit title/body widgets. A real-SDK mocked 401 retained the old draft and exposed only a safe error. Current quota code/type variants are covered, including unknown/missing codes with `insufficient_quota` type. Source guards prevent invalid requests before any client is opened.
- Settings tests verified cross-process rereading of an isolated temporary `.env`, key/model revision changes, model-only updates preserving other settings/comments, atomic failure preserving previous config, and exclusion of authentication overrides. CLI tests verify no echo, noninteractive refusal, cancellation, safe 401 handling and check-only/no-test semantics. No test writes the user's actual `.env`.
- Real Chrome loaded both `http://127.0.0.1:8501` and the authenticated external HTTPS app, navigated to the writer and clicked **Đọc lại cấu hình AI**. Both correctly explained the missing key and disabled probe/generation. Local had one inline key field; shared had zero inline key fields. The API-key creation links were correct, the old restart instruction was absent, and neither page had browser exceptions/red error alerts.
- Both server processes were refreshed for the new AI code; the external URL was preserved. No real paid OpenAI request, real generated article or new production Word export was performed. Successful billing, actual account/model permission, Chinese output quality and real end-to-end generation remain unverified until the user creates and enters a valid API key locally.

Earlier validation records follow for history.

## Source-status repair and authenticated sharing checked on 2026-10-23

The reported warning listed every publisher. Fresh CLI discovery could still read most sources, so that exact session failure was not reproduced. Two concrete defects were fixed: an individual failed RSS endpoint incorrectly labelled its entire publisher incomplete, and failed independent DNS confirmation was cached for five minutes. The latter could keep an old app process failing after a transient VPN/DNS problem while a fresh process succeeded. Successful DNS confirmation is still cached; failures are now retryable immediately. This is a plausible cause of the reported all-source failure, not a claim that its original network state was captured.

Public discovery now distinguishes wholly failed publishers, partial publishers and successful publishers. Endpoint diagnostics expose safe reasons (DNS, TLS, timeout, HTTP, blocked access, empty/JavaScript index) without response bodies or secrets. A bounded retry handles transient transport/502/503 errors. The dashboard shows read-source counts and an endpoint status table while retaining findings from surviving sources. Publication provenance and date filtering remain enforced; blocked portals are never silently labelled searched.

The user selected a temporary external link with an authenticated editorial area, followed by later 24/7 hosting. Added `run_share.py`, an isolated loopback server on 8502 plus an HTTPS Cloudflare Quick Tunnel, leaving local 8501 running. Both detached processes have parent PID 1. A generated team password and its scrypt hash are owner-readable files under ignored `.runtime/share`; neither is included here. Authentication runs before database/workspace initialization, expires after eight hours, limits attempts, clears the session on logout/credential rotation, and hides API-key mutation remotely. Shared login does not establish each named reviewer's legal/editor credentials.

cloudflared 2026.10.3 was downloaded from the official Cloudflare GitHub release and matched its SHA-256 asset digest. The first tunnel received a URL but did not establish an edge connection because this VPN blocks the Go SRV DNS path. That attempt was not accepted as a working deployment. The opt-in `--vpn-dns` workaround resolves fixed official Cloudflare edge hostnames over authenticated HTTPS and supplies fresh public addresses through cloudflared's internal `--edge` option. Built-in edge TLS verification stays enabled; no OS DNS/VPN changes were made. The launcher now waits for actual tunnel readiness before reporting success. This workaround and Quick Tunnel remain temporary, with no uptime guarantee.

Final checks:

- **168 tests passed**, no failures or skips: core16, research31, Google16, visuals6, launcher8, Streamlit UI7, public provider27, publication templates10, search integration14, local settings4, access control12, production launcher6, share launcher11. Complete run: 24.662 seconds. Share tests do not signal real processes or read real passwords.
- Ruff lint passed; Ruff formatting check passed for all 30 Python files; compileall, `pip check`, and macOS shell syntax checks passed.
- Real Chrome at the local URL successfully searched both **đầu tư Trung Quốc** and **khu công nghiệp**, each showing four current story groups in this run, with no page exceptions/red error alerts. Counts vary with the live feeds and connection availability.
- Real Chrome through the external HTTPS URL showed zero search fields before login, then completed a real **khu công nghiệp** search after login. Four source story cards linked to Báo Đầu Tư, CafeF and VnExpress. No API-key inputs appeared remotely. Logout returned to the protected login screen; no browser page errors or red error alerts occurred.
- External HTTPS `/` and `/_stcore/health` returned HTTP 200. Local app remains `http://127.0.0.1:8501`; the current temporary external URL is recorded in `.runtime/share/tunnel.json` and printed by `run_share.py status`.
- Dockerfile, Compose and Render Blueprint prepare one authenticated instance with a persistent `/data` disk. Deployment entrypoint rejects missing auth, invalid ports and unwritable storage before binding. YAML/schema checks passed. Docker is not installed here, so image build/Linux execution and real Render deployment were **not** run. No paid cloud resources were created.

Remaining limits: public RSS/current indexes are not a full historical index. MOF/VBPL JavaScript shells, some access-blocked portals and intermittent timeouts remain explicitly reported. Paid Tavily, OpenAI drafting and real Google OAuth still require credentials and live checking. The temporary URL requires the Mac awake/online and changes when its tunnel is recreated; 24/7 hosting needs the user's hosting account and persistent disk. Human claim, legal-effect and publication approval remain mandatory. No WeChat publication or production Word article export was performed during this repair.

Earlier validation records follow for history.

## Search completion checked on 2026-10-23

The screenshot's error was a mandatory Tavily key gate. A second real failure was found in network verification: this Mac's VPN resolves public publisher names to benchmark/ULA addresses, so the old guard rejected legitimate sources even though normal HTTPS worked.

Implemented:

- Automatic no-key discovery from fixed publisher RSS feeds and government/legal indexes; optional explicit public/Tavily modes. Automatic mode can fall back from a failing Tavily connector. The UI describes the latest-feed coverage rather than claiming a full historical web index.
- Original-page date verification remains mandatory for the recent shortlist. RSS/provider dates only order candidates. Proven old originals are excluded and unproven dates remain in the verification queue.
- Explicit China queries require China relevance and investment/economic context. Focused industrial-park searches require actual industrial-park/KCN aliases. Tests reject unrelated crime, celebrity, generic IPO, gasoline and construction-only matches.
- Correct CafeF semantic publication spans, tested original-header fallbacks for five publishers, same-page www/HTTPS aliases, and actual-article body selectors. Short legal IDs and Chinese headings are retained.
- Exact registered publisher hosts behind benchmark/ULA VPN DNS are independently corroborated through HTTPS public DNS. Loopback/RFC1918/link-local hosts, arbitrary IPs, unrelated redirects and HTTPS downgrades stay blocked. No system DNS/VPN settings changed.
- Local password-field setup for optional API keys: atomic .env writes, 0600 permissions, no key prefilling, no secrets in returned status or Git. AI drafting is clearly disabled without its key while manual writing/review/export remains available.
- Kept typed keywords and filter snapshots across navigation/category changes; cleared stale results on failed searches. Coverage, timing, candidate counts and verification states are visible. Empty/blocked indexes do not count as successful reads, and the UI distinguishes unavailable sources from zero matching news. Impact keywords use word boundaries so names such as Kim Anh do not create a false M&A tag.

Validation:

- **129 tests passed**, no failures or skips: core16, research31, Google16, visuals6, launcher8, Streamlit UI6, public provider21, publication-date templates10, integration11, local settings4.
- Ruff lint and formatting, compilation, pip dependency check all passed. No dependency additions were required.
- Live public search, with no Tavily or OpenAI keys, was executed through the actual Chrome UI for **đầu tư Trung Quốc** and **khu công nghiệp**. Both returned original source links, had no page exceptions/red error alerts, and did not show the old missing-Tavily-key error.
- Live discovery/date checks: the default China query produced 3 original URLs forming 2 recent official-source story groups in about 4–5 seconds. The focused industrial-park query produced 7 verified recent URLs and excluded 1 proven older article in about 5–6 seconds. These are observations for the current feed contents, not guaranteed fixed result counts.
- Source saving, source/date editing, revision/claim review and two-role Word export remain covered by isolated UI tests. Test API settings are isolated from the user's real .env.
- Current public-access checks also found SBV returning a rejection page, MOF/VBPL serving JavaScript shells without article links, and a TLS failure for VBPL.MOJ. Those sources are reported unavailable/partial, not successfully searched. Văn bản Chính phủ and Công báo exposed genuine document URLs.
- Paid Tavily calls, live OpenAI drafting and real OAuth synchronization were not run because credentials were not supplied. Optional keys can now be entered locally in the dashboard. Human claim/legal review remains required.
- Server restarted with the final code and remains at **http://127.0.0.1:8501**.

Earlier validation records follow for history.

## Connection fix checked on 2026-10-23

The reported symptom was that the local page could not open / lost connection. No Streamlit process or listener existed on port 8501. The 70 existing tests and an additional isolated source/draft UI flow passed before the fix; no app exception was reproduced in those workflows.

Added `run_local.py` and updated the macOS/Windows launchers. The server now detaches from the calling shell/chat, redirects output to a private local log, records its PID and creation identity, reuses an existing healthy instance and refuses to stop unrelated processes. Added `stop_mac.command`; status/restart/stop are also available through the launcher CLI. It does not install an auto-start service or start at boot.

Follow-up validation:

- **78 tests passed**: the existing 70 plus 8 launcher lifecycle tests; no failures or skips.
- Ruff lint and formatting, compilation, `pip check`, and `bash -n start_mac.command stop_mac.command` passed.
- The real launcher exited successfully while the Streamlit server continued with parent PID 1 and its own process group.
- A second launcher invocation reused the same PID and did not create a duplicate server.
- A new shell independently confirmed launcher status and HTTP **200 / ok** at `http://127.0.0.1:8501/_stcore/health`.
- Headless Chrome loaded the actual page, waited for the search field, search button and metrics, and reported no page errors. The URL remains **http://127.0.0.1:8501**.
- Lifecycle tests cover detached shell-free launch, idempotence, occupied ports, corrupt/stale PID state, PID reuse, identity checks before signalling, startup timeout and log messages without secrets.
- Real Windows process management remains untested on this Mac. Live API/OAuth limitations listed below are unchanged.

The earlier implementation validation is retained below.

## Passed

- Python 3.14 project virtual environment installed from `requirements.txt`, with Ruff from `requirements-dev.txt`. `python -m pip check`: no broken requirements.
- `python -m ruff check .`: all checks passed (E4/E7/E9/F rules).
- `python -m ruff format --check .`: 13 Python files already formatted.
- `python -m compileall -q app.py core.py research.py google_docs_sync.py visuals.py tests`: exit 0.
- `python -m unittest discover -s tests -v`: **70 tests passed**, no failures or skips.
- Breakdown: 16 core tests, 30 research tests, 16 Google API contract tests, 6 visual tests, 2 Streamlit AppTest smoke tests. External API calls are mocked; workspaces are temporary.
- The smoke workflow actually enters a source, confirms date evidence, saves a Chinese draft, reviews each enumerated claim, records editor and lawyer approvals, verifies dirty edits block export, and appends to a temporary Word master. It also checks navigation, source entry, offline missing-key state, date range validation and blank map coordinates.
- Failure/recovery checks include concurrent Word exports, content deduplication across different article IDs, preserved prior Word paragraph XML, a file-written/DB-failed retry, missing master, additive legacy schema migration, immutable exported approvals, current-source changes invalidating sign-offs, and retained approval/revocation history.
- Google mocks cover unreadable configured masters, ambiguous discovery, lost folder/Doc create responses with delayed discovery, interrupted folder moves, missing revision IDs, concurrent-edit rejection, write timeout reconciliation, tabs, UTF-16 hyperlink ranges, missing remote markers and local saved flags. No real Google document was created or edited.
- `bash -n start_mac.command`: passed. Windows script was updated but has not been executed on Windows.
- Local server started with `python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false`. Exact printed URL: **http://127.0.0.1:8501**.
- Real headless Chrome loaded the running dashboard: HTTP health endpoint returned **200 / ok**, page title matched, no browser page errors. Desktop screenshot was visually inspected.
- A synthetic approved Word sample was rendered using the bundled LibreOffice and document renderer, then its single page was visually inspected. Corrected inherited title borders, hidden control markers and explicit CJK fonts. The renderer's temporary fontconfig pointed at this Mac's installed PingFang/Hiragino fonts; the system font library was not changed. No synthetic sample was appended to the user's real master.

AppTest prints Streamlit's expected bare-mode `ScriptRunContext` diagnostic. It does not indicate a test failure. Final test run had no SQLite resource warning.

## Needs credentials or human checking

- Optional Tavily and OpenAI keys were not configured. Public RSS/index search and original-page extraction have now been tested live as described above. Paid Tavily calls, OpenAI model availability/cost/quota and live Chinese generation remain untested. Configure optional keys locally through the dashboard or `.env`.
- No OAuth Desktop Client was present. Real browser consent, account permissions and end-to-end Google appends still need the user's Google account and local `google_oauth_client.json`.
- The requested `~/Documents/FRIC_LAW_WeChat_Studio/references/` folder did not exist before application startup; no reference `.docx` files were available. The existing `STYLE_GUIDE.md` was inspected and preserved. The app creates an empty references directory for later use.
- A lawyer/editor must confirm the meaning of each evidence excerpt, current law, amendment/replacement history, effective dates, applicability and any transition clauses. Pattern checks and exact-string matching do not prove legal correctness or semantic support.
- Project values, coordinates, novelty of an event, Chinese editorial quality, one-topic scope and any client confirmation remain human decisions. Local role sign-offs record names and roles; they do not authenticate professional credentials.
- No real approved article was supplied, so the real Word master was not created or changed. No WeChat publishing was performed.

## Primary API references checked

Tavily's provider date is a discovery hint; explicit original-page publication evidence drives the local date gate. See the [official Tavily search reference](https://docs.tavily.com/documentation/api-reference/endpoint/search).

Google appends use required revision control and tab-aware end-of-segment insertion, as defined in the [Docs batchUpdate reference](https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/batchUpdate) and [Docs request types](https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/request).

VPN DNS corroboration follows the [Google Public DNS JSON API](https://developers.google.com/speed/public-dns/docs/doh/json); only fixed publisher hostnames are sent, with the client-subnet hint suppressed.
