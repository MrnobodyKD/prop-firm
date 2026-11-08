# Mega Funded Rebrand Report — 2026-11-08

## Phase results

- **Phase 1 — Brand sweep: PASS within the permitted source files.** Rebranded templates, application notices, email defaults and subjects, payment return/webhook URLs, sitemap URLs, robots files, and the specified challenge timeline currency. Preserved the intentional `app.py:141` default `sqlite:///tragene_funded_new.db` exactly. Old strings remain in untouched pre-existing reports and `fix_columns.py`; see grep results.
- **Phase 2 — Homepage: PASS for requested copy and data.** Rebuilt `templates/index.html` with the requested sections, four plan selectors, five size choices with no $100K Instant option, plan pricing/rules, text dashboard features, corrected FAQ facts, restored Organization/Website/FAQ JSON-LD schema, and login-aware challenge CTAs. Pricing and size behavior were inspected in the picker JavaScript; an interactive browser check was not run.
- **Phase 3 — Legal and information pages: PASS.** Replaced Terms/Legal identically, and rewrote Privacy, Refund, and Contact. Terms name Mega Funded as the service only and make no entity, address, jurisdiction, or payout guarantee claims. Existing FAQ template received the brand, canonical, and support-email sweep; database FAQ entries remain a follow-up.
- **Phase 4 — Images and logo: PASS.** Added `static/images/favicon.svg`; replaced logo image placements with text wordmarks; removed the named logo, banner, junk journal, old favicon assets, and six dashboard screenshots. No template references to the six screenshots remain.
- **Phase 5 — Scope: PASS.** No database, `.env`, model, migration, route, or server-side payment implementation edits were made. `scratch/`, `admin_routes.py.bak`, and `93fcb124ff91,` were removed as requested. Changes remain uncommitted.

## Verification

- Activated the project environment before Python checks; `py_compile` passed for `app.py`, `auth.py`, `email_service.py`, `rule_engine.py`, and `admin_routes/admin_challenges.py`.
- Jinja parsing passed for all 90 templates. `terms.html` and `legal.html` are byte-identical.
- `git diff --check` passed.
- Render smoke check used a disposable SQLite database at `%LOCALAPPDATA%\Temp\mega_funded_rebrand_test.db`; no production database was used. `/`, `/faq`, `/contact`, `/terms`, `/privacy`, `/refund-policy`, `/login`, and `/register` returned 200. `/user/dashboard`, `/admin/`, and `/user/challenge/1/buy` redirected to login for the anonymous test client. Authenticated dashboard/admin/buy rendering, coupon behavior, and manual/crypto payment sections were not verified.
- The prompt-listed `/refund` URL is not an existing route; the site route is `/refund-policy`, and the updated footer/legal links use that existing route.
- Database-backed FAQ content and the live database challenge/payment/notification records were not inspected or changed. The challenge picker uses the prompt's specified values; challenge buy-page rendering against live rows was not verified.

## Grep verification

Command searched repository text (excluding `.git` and database files) case-insensitively for `kisiki`, `kisikicapital`, `tragene`, `tragenefunded`, `tragene.co@gmail.com`, `₹`, `Dar es Salaam`, `+255`, `kisikicapital.com`, `tragenefunded.com`, `trade.kisikicapital.com`, `youtube.com/@kisikicapital`, `tragene_banner.png`, `logo.png`, and `thaurusguru`.

Full output:

```text
./app.py:141:db_url = os.getenv('DATABASE_URL', 'sqlite:///tragene_funded_new.db')
./five-fixes-report-2026-11-07.md:39:**Changes:** In `templates/index.html`, the non-FAQ landing rules now say Kilimanjaro Phase 2 6%, Everest 8%, and the requested daily and overall loss limits for all four plans. The dashboard preview URL is `trade.kisikicapital.com/dashboard`; the invented Premier tagline was removed; the non-FAQ prohibited-practice list no longer uses latency-arbitrage or tick-scalping terms.
./five-fixes-report-2026-11-07.md:41:**Verification: PARTIAL / FAIL for the requested whole-file parity checks.** The corrected non-FAQ landing section contains the new values. However, the homepage FAQ block currently contains the old Phase 2 5%, Everest 10%, Instant daily loss 5%, and the terms latency arbitrage/tick scalping. The task explicitly said not to edit the FAQ block, so it was left unchanged. Consequently, grep for those old values and terms across the entire `templates/index.html` still returns FAQ hits, and landing-to-FAQ parity cannot pass without changing that block. The changed diff introduced no Tragene, rupee, UPI, or MT5 copy.
./fix_columns.py:16:for path in ("instance/tragene_funded_new.db", "tragene_funded_new.db"):
./payment-build-report-2026-11-07.md:20:- Searched user templates for `₹`, `+91`, UPI, Rupay, NEFT, and IFSC; no matches remain. Checkout contains no Cashfree SDK, INR literal, or gateway surcharge.
```

The SQLite default is the one intentional match. The other matches are in pre-existing untracked files outside the permitted edit list and were left intact, so the literal whole-repository zero-match requirement is **not fully met**. Database file contents were excluded from text grep because the database is explicitly out of scope.

## Owner follow-ups

- Update live database FAQ rows, challenge rows, payment method rows, notification templates, and the blog post author in the admin panel.
- Set `RESEND_FROM_EMAIL` and any related keys in the server `.env`.
- Provide real legal entity name, registered address, and jurisdiction if they should appear in legal terms; none were supplied, so none were invented.
- Decide how to handle old brand strings in the pre-existing reports and `fix_columns.py` if a literal repository-wide grep must pass.
