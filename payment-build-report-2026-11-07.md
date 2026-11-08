# Payment build report — 2026-11-07

Branch: `main`. Changes remain uncommitted. The earlier five fixes were preserved.

## Part A — Generic payment methods: PASS

- Added the data-driven `PaymentMethod` model, including JSON details, currency, USD-per-local-unit rate, optional QR/help images, activation, and ordering.
- Added migrations `d10000000001` and `d10000000002`. Applied both upgrades to a disposable legacy-shaped SQLite fixture; verified the new table, columns, and foreign key.
- Added admin list/create/edit/activate/deactivate/delete routes and the payment-method manager page. Delete is rejected when any payment references the method.
- Image uploads are signature-checked and limited to 5 MB, stored under `instance/payment_method_assets`, and served behind login.
- Test client created, edited, and deactivated a method; active methods appeared on checkout and deactivated methods disappeared. Admin pages returned HTTP 200.
- Upload size/type rejection boundaries were reviewed in code but not exercised with large or malformed upload fixtures.

## Part B — Checkout and payout fields: PASS

- Replaced the Cashfree checkout SDK and India-specific rails with NOWPayments crypto and active admin-managed manual methods. The Cashfree order endpoint remains available but is no longer linked from checkout.
- Removed the 2% surcharge. USD pricing, coupon validation/preview, discounted totals, and per-method local-currency estimates are shown without a hardcoded exchange rate.
- Checkout renders the stored phase targets, daily/overall loss limits and modes, minimum days, duration/no-expiry, phase leverage and notes, profit share, payout schedule, holding/news/EA rules, lot/consistency rules, and safety/payout fields.
- Replaced the payout IFSC input with SWIFT/BIC and bank address; the request handler stores both.
- Searched user templates for `₹`, `+91`, UPI, Rupay, NEFT, and IFSC; no matches remain. Checkout contains no Cashfree SDK, INR literal, or gateway surcharge.
- Coupon test: a 20% USD coupon on a $99 challenge recalculated to $79.20.

## Part C — Manual payments: PASS

- Manual submission stores one `pending` Payment with transaction reference, USD/local amount, message, and screenshot outside `static`; it does not create a challenge.
- Admin review accepts only pending manual claims. Approval uses the shared `provision_challenge()` path; repeat approval did not create another challenge. The shared `purchase_confirmation` email step was invoked once in a mocked email test. No email was sent externally.
- Rejection leaves the claim rejected with no challenge; a new submission was accepted afterward.
- Evidence access checks login and ownership: logged-out access redirected without returning a file, a different user received 404, and the owner/admin route returned the file.
- The manual claims view includes trader, challenge, method, USD/local amount, reference, message, date, protected evidence link, and approve/reject actions.

## Part D — NOWPayments: UNTESTED (sandbox credentials not configured)

- Added generic `crypto_gateway.py` with sandbox-default API host, configurable host, invoice creation, IPN HMAC-SHA512 verification, and server-side payment-status lookup.
- Added `/nowpayments-webhook`. It verifies the signature, re-fetches provider state, verifies order/payment identity and USD amount, and provisions only a `finished` payment that is still `waiting`. Partial payment becomes pending manual review; failed/expired states do not provision. Duplicate delivery is idempotent.
- Mocked tests passed for valid finished IPN, bad signature, partial payment, duplicate finished IPN, and discounted invoice creation. The mocked 20% invoice stored the coupon ID and $79.20 expected amount.
- A real sandbox invoice/end-to-end payment was not attempted because credentials were absent. Required environment variable names are listed below.
- The invoice response is stored with its expiry when supplied. The implementation adds no local expiry cutoff when the provider supplies none. NOWPayments describes hosted invoices as having no expiration date; in that case the continue link remains available until the provider reports an expired payment. [NOWPayments invoice guidance](https://nowpayments.zendesk.com/hc/en-us/articles/18393446018461-Invoices-and-payments)

## Part E — Payment records and views: PASS

- Added nullable payment rail, method snapshot, reference, receipt/evidence, local amount/currency, invoice URL, and expiry fields with a migration; existing Cashfree rows retain nullable compatibility.
- Admin analytics now filters manual, crypto, Cashfree history, and pending records; rows show user/challenge/method/amount/reference/status/date and link to protected detail/evidence or receipt views.
- User challenge details show linked payment evidence and include the Payment History button. The new `/user/payments` page uses `templates/user/payment_history.html`; it is text-only, contains no image tags, displays receipt links, and is scoped to the signed-in user.
- Verified the same manual payment reference/amount/status in the user and admin views; another user's payment history did not expose the record.

## Part F — Invoice continuation and lazy expiry: PASS

- The History page provides Continue Payment only for a waiting crypto payment with an invoice URL and no provider expiry, or an expiry still in the future. Past provider expiries are marked `expired` when History loads.
- Tested future expiry (continue link shown), past expiry (status changed to expired and link absent), and manual pending (no continue link).
- No background expiry job or separate time cap was added.

## Regression results

- Mock Cashfree pending payment with provider still pending: remained pending and created no challenge. Mock pending Cashfree payment with verified provider success: completed and provisioned once.
- Two-phase route progression: phase 1 passed → phase 2 request/approval → phase 2 passed → funded request/approval → funded phase 3. The test arranged the passed state directly; it did not replay MT5 trades or change progression code.
- One-phase Everest route progression reached funded phase 3.
- Instant checkout returned HTTP 200; instant payout eligibility returned eligible for a funded instant fixture.
- Admin Users, Challenges, Payments, Payouts, Coupons, and Analytics pages returned HTTP 200. Checkout, manual-payment, history, payment-history, payment-method, and manual-claim pages also returned HTTP 200.
- Venv `py_compile` passed for edited Python modules and migrations. All 17 edited templates parsed through the app Jinja environment. `git diff --check` passed.
- App booted against disposable SQLite. Existing SQLAlchemy relationship-overlap warnings and Redis-unavailable memory-fallback warning were emitted; no mapper initialization error remained.
- All disposable SQLite databases and test evidence files were removed after verification. No production database, live dashboard, external payment API, or real money was used.

## Deployment configuration

- `NOWPAYMENTS_API_KEY`
- `NOWPAYMENTS_IPN_SECRET`
- `NOWPAYMENTS_API_BASE_URL` (optional; defaults to the NOWPayments sandbox host)

## Leftovers

- Configure sandbox credentials and run a real sandbox invoice/IPN cycle before enabling crypto checkout in a deployment.
- The existing Cashfree path remains in place for compatibility and is not connected to the new checkout.
- Existing ORM overlap warnings are outside this payment change and were left untouched.
