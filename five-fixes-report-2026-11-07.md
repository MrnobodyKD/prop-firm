# Five Fixes Report — 2026-11-07

## Fix 1 — Everest progression

**Problem:** Passed one-phase challenges at phase 1 were offered a Phase 2 request that the server rejected, blocking funded progression.

**Changes:** `user_routes.py` now accepts a funded request for a passed one-phase phase-1 account. `templates/user/user_dashboard.html` shows the funded request for one-phase challenges and retains the Phase 2 request for two-phase phase-1 challenges.

**Verification: PASS.** In the project venv against a disposable SQLite database, Flask test-client checks rendered the one-phase funded and two-phase Phase 2 cards, submitted and persisted the one-phase `funded` request as pending, and approved it through the admin action. The challenge became funded at phase 3 with `funded_at` set. Payout eligibility passed after setting a simulated elapsed payout cycle and qualifying profit. The Instant phase-3 account displayed no progression card.

## Fix 2 — Clearing flags on funded accounts

**Problem:** Both admin clear paths restored every held account to `active`, so funded accounts could be judged against evaluation targets again.

**Changes:** Both clear paths in `admin_routes/admin_challenges.py` now restore `funded` status and monitoring status when `current_phase == 3`, otherwise `active`, and reset risk score to zero. `rule_engine.admin_clear_flag` had no callers and was removed from `rule_engine.py`.

**Verification: PASS.** On the disposable database, the `/api/challenge/<id>/clear-flag` route and the `clear` action both restored phase-3 accounts to `funded` with risk score zero. The route restored a phase-1 account to `active`. After setting a cleared funded account above 8% phase profit and running `rule_engine.check_rules`, it remained `funded`.

## Fix 3 — Admin navigation

**Problem:** The homepage Dashboard link sent admins to the trader dashboard, and the trader sidebar had no link back to admin.

**Changes:** `templates/index.html` now uses the existing `session['is_admin']` flag for the homepage Dashboard target. `templates/user/base.html` adds an Admin Panel link in both desktop and mobile sidebars only for admins.

**Verification: PASS.** Rendered homepage checks showed `/admin/` for an admin and `/user/dashboard` for a normal user. The admin could still GET `/user/dashboard` and saw Admin Panel. The normal user did not see Admin Panel.

## Fix 4 — Admin navigation data refresh

**Problem:** Turbo intercepted admin sidebar navigation, preventing page scripts that run on full loads from refreshing page data.

**Changes:** Removed the Turbo script tag from `templates/admin/base.html`; the turbo-cache-control meta tag and existing theme initialization code remain.

**Verification: PASS for server-rendered navigation checks.** In sequence, `/admin/users`, `/admin/challenges`, `/admin/payments`, `/admin/payouts`, `/admin/coupons`, and `/admin/analytics` all returned HTTP 200 from the test client. Their responses did not include the Turbo script. The theme toggle markup and DOMContentLoaded initializer are still present. No browser session was used, so client-side AJAX freshness and browser console output were not directly observed.

## Fix 5 — Landing page copy

**Problem:** The non-FAQ rules copy contained outdated challenge targets, risk limits, dashboard URL, and prohibited-practice wording.

**Changes:** In `templates/index.html`, the non-FAQ landing rules now say Kilimanjaro Phase 2 6%, Everest 8%, and the requested daily and overall loss limits for all four plans. The dashboard preview URL is `trade.kisikicapital.com/dashboard`; the invented Premier tagline was removed; the non-FAQ prohibited-practice list no longer uses latency-arbitrage or tick-scalping terms.

**Verification: PARTIAL / FAIL for the requested whole-file parity checks.** The corrected non-FAQ landing section contains the new values. However, the homepage FAQ block currently contains the old Phase 2 5%, Everest 10%, Instant daily loss 5%, and the terms latency arbitrage/tick scalping. The task explicitly said not to edit the FAQ block, so it was left unchanged. Consequently, grep for those old values and terms across the entire `templates/index.html` still returns FAQ hits, and landing-to-FAQ parity cannot pass without changing that block. The changed diff introduced no Tragene, rupee, UPI, or MT5 copy.

## Regression

- **Two-phase progression:** PASS. Test-client flow covered Phase 1 passed → Phase 2 request → admin approval → phase 2 → simulated pass by local field update → funded request → admin approval → funded phase 3.
- **One-phase Everest progression:** PASS. Funded request submitted, persisted pending, and approved to funded phase 3.
- **Instant buy and payout eligibility:** PASS. Instant buy page returned HTTP 200; Instant payout eligibility passed with simulated qualifying profit and elapsed cycle.
- **Checkout with coupon:** PASS with a mocked Cashfree client. A local order using a 20% coupon persisted with the coupon ID and expected amount of USD 81.60. No Cashfree network call or real payment was made.
- **Admin pages:** PASS for HTTP 200 on Users, Challenges, Payments, Payouts, Coupons, and Analytics; client-side fresh-data behavior and console errors were not browser-tested.
- **App startup:** PASS. Imported and requested `/` with `DATABASE_URL` overridden to the disposable SQLite database; homepage returned HTTP 200 and edited Jinja templates loaded. Startup emitted existing SQLAlchemy relationship warnings and a Redis-unavailable fallback warning, but no startup error.
- **Python compilation:** PASS. Ran `python -m py_compile user_routes.py admin_routes\\admin_challenges.py rule_engine.py` in the activated project venv.
- **Jinja parsing:** PASS. Loaded `index.html`, `user/base.html`, `user/user_dashboard.html`, and `admin/base.html` through the app Jinja environment.
- **Diff whitespace:** PASS. `git diff --check` returned no errors.
- **Disposable database:** Removed the locally created `instance/five_fixes_disposable_20261107.sqlite` after verification.

## Leftover

- Fix 5’s whole-file old-number grep, prohibited-term removal, and landing/FAQ parity remain unresolved because the task simultaneously said the FAQ was already correct and explicitly prohibited editing it, while the repository FAQ contains the old values and terms. The FAQ and `faq.html` were left unchanged.
- Admin sidebar freshness and browser console behavior were checked through server-side requests only; no browser was used to navigate a live dashboard.
- Startup warnings described above remain outside the requested fixes.
- No production database, live dashboard, or real-money payment was used. No files outside the requested sections were edited. All tracked changes are uncommitted; pre-existing untracked repository items were left untouched.
