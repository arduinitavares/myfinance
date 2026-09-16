# 2026 financial research dataset and sync

Date: 2026-09-16
Status: Agreed research direction; written design awaiting Operator review
Baseline: `main` at `dc9c4b8`

## 1. Purpose and decisions

Build a trustworthy local dataset for 2026, keep it updated through repeatable manual syncs, and use analysis to discover which MyFinance features are worth building.

The Operator approved this sequence: collect, validate, explore, record findings, and choose features from the evidence. The first deliverable is the research dataset and its quality report. A dashboard, financial score, forecast, or Alfred notification system is not a prerequisite.

The selected approach combines preserved provider JSON with a separate SQLite research database. JSON retains evidence; SQLite supports identity constraints, revision tracking, and repeatable queries. CSV-only exports make corrections and repeated imports harder to reconcile. Direct writes into MyFinance's existing consolidated record would mix exploratory data with reviewed data too early.

This is a deliberate, limited extension of the July operating model: Banco MCP supplies a research dataset. Its automatic observations do not become Operator-approved Financial Events. The production import/review workflow and its database remain unchanged.

## 2. Initial scope

- Discover the bank connections already accessible through Banco MCP and enumerate their BANK and CREDIT accounts. Capture all accessible accounts in those types; report inaccessible connections explicitly.
- Fetch available 2026 bank-account and credit-card transactions.
- Preserve account metadata and capture current balance observations, including original currencies and source timestamps when supplied.
- Keep sync history, provider revisions, validation issues, and local research annotations.
- Produce reproducible local analyses and an evidence-based feature discovery log.

Investment holdings, investment movements, loan contracts, itemized bill endpoints, historical file ingestion, scheduled jobs, webhooks, new bank connections, provider category edits, and changes to the application UI are later scope decisions. An investment institution's BANK account cash balance is not its investment portfolio.

Existing CSV/PDF history is not imported or read in this phase. Later comparison with it must detect overlapping evidence rather than create duplicate Financial Events.

### 2026 boundary

Transaction requests begin at `2026-01-01` and end at the earlier of the sync date in `America/Sao_Paulo` and `2026-12-31`. The analytic transaction date must fall within that requested interval. Future-dated transactions are excluded until eligible. Re-syncs after 2026 can still capture revisions to 2026 records, without requesting 2027 transactions.

The first response-validation step identifies the provider's transaction-date field and its meaning. Date-only values remain dates. Timestamp values retain their original value and offset; a derived analysis day uses `America/Sao_Paulo`. Purchase dates, posting dates, and bill dates remain distinct when available. The chosen primary date and conversion rule are versioned with the adapter; dates are not silently substituted for one another.

Only in-scope transaction objects are retained. An unexpectedly out-of-range row is omitted and counted. A row whose year cannot be established is not stored; its page and validation issue are recorded without retaining that row. Thus the archive preserves original eligible objects, not necessarily a byte-for-byte copy of a whole HTTP response. Each capture records whether filtering occurred. This qualification must also appear in export metadata.

Account metadata describes the account as observed. Balances are point-in-time observations collected during 2026; later corrections to transaction history do not introduce 2027 balance snapshots into this dataset. Current balances do not establish January opening balances or historical daily balances.

## 3. Isolation and storage

Use one private root outside the existing import scanner's `supported/` tree:

```text
bank_files/research/2026/banco_mcp/
  research.db
  raw/<run-id>/<capture-id>.json
  reports/
  notebooks/
  backups/
```

The existing `/bank_files/` ignore rule covers the database, JSON, notebooks with real outputs, reports, and backups. Paths use internal IDs or non-identifying aliases, never names, account numbers, card numbers, or credentials. Use restrictive local directory/file permissions. Git ignore is an exclusion rule, not encryption.

Reusable collection code, analysis definitions, empty notebook templates, documentation, and synthetic tests are tracked in the repository. Real datasets and rendered analyses remain under the private root. The implementation plan will select code locations consistent with the repository's existing Python tooling.

The research process opens only its explicitly configured database. It rejects the production database path and databases without the expected research schema marker. It must not import backend startup modules that initialize or migrate the application database. Only one sync writer may run at a time; analyses open the research database read-only and use a consistent snapshot.

Original eligible provider objects are immutable evidence. SQLite is the queryable representation, with explicit links back to that evidence. Credentials and HTTP authorization headers are never part of captures. Research backups include the database and referenced captures; restoration validates their hashes and schema before use.

## 4. Data model

These are internal concepts, not claims about provider response field names.

| Concept | Responsibility |
| --- | --- |
| Sync run | Start/end time, requested interval, adapter version, overall result, counts, and error codes. |
| Account fetch | Connection/account/resource identity, date window, page progress, capture references, and completed/failed state. |
| Capture | Eligible provider JSON plus safe request metadata, object locator, content hash, capture time, and omitted-row counts. |
| Connection and account | Source identifiers, type, currency when supplied, first/last observation, and optional Operator-assigned aliases/holder mapping. Preserve changed metadata in captures. |
| Source transaction version | Provider identity scoped to its source/account, original payload hash, normalized fields, first observation, and links to captures. |
| Current source transaction | Latest accepted version of that source identity, available lifecycle state, and provenance. |
| Balance observation | Account, balance kind, amount, currency, observed-at time, source as-of time when provided, and evidence. |
| Research annotation | Local classification, match proposal, decision, author, and the exact source version reviewed. |
| Quality issue | Affected internal record/window, stable issue code, severity, and resolution evidence. |

Store monetary values as exact decimal strings and calculate with decimal arithmetic. Preserve the original amount representation and currency. Do not introduce binary-float rounding into normalization. Unknown currencies remain unknown; preserve unfamiliar currency codes and flag them. Do not add unlike currencies or silently apply an exchange rate.

A repeated transaction with the same scoped source identity and unchanged payload links to the existing version. A changed payload creates a revision and advances the current-source pointer only after validation. Identical raw objects may share a content hash while each fetch still records its own observation.

Provider identifiers are not proof of an economic match across different sources or reconnections. Maintain a separate local account identity and explicit source bindings. A newly observed source binding begins unresolved until the Operator maps it; overlapping histories cannot silently enter a consolidated total. Potential duplicate bindings are flagged, never merged solely on bank name, last digits, date, or amount.

If a record has no usable source transaction ID, preserve its eligible object with capture/position identity and flag it for review. Do not insert it automatically into current-source transaction totals. Identical purchases can share date, amount, and description, so a fingerprint alone cannot safely prove identity.

Sync never overwrites a research annotation. If its underlying source version changes, the annotation becomes stale and needs review. Pending-to-posted records sharing an ID become revisions. If their IDs differ, flag a possible replacement and keep them distinct until resolved. A missing record in a later fetch is not a deletion. Explicit deletion/reversal evidence, if the provider supplies it, is retained as such; otherwise the record's disappearance remains an observation gap.

## 5. Manual sync behavior

1. Validate the credential's presence, private storage root, schema, exclusive writer lock, and requested 2026 window. Do not print credentials or start a provider mutation.
2. Use `/connections/list` and `/accounts/list` to discover accessible data. Compare with the last successful inventory. Partial inventory responses never retire previously known accounts.
3. Fetch `/transactions/list` per account in calendar-month windows clipped to the requested interval, using `detail: raw`, explicit pages, and a documented page size. Retrieve bank and card accounts separately.
4. Capture eligible objects and stage normalization. A window is accepted only after every page has been retrieved and validated and pagination has an established termination condition.
5. In one SQLite transaction per account/window, publish its accepted versions, current pointers, provenance links, quality issues, and completion marker. A failed window keeps its last successful current representation.
6. Capture balances independently with `/accounts/balance`, initially one account per request. Failure or unsupported card balance is recorded as unavailable, never zero. Account-list balances may be retained as a separate observation type with their provenance; they are not interchangeable with the dedicated endpoint.
7. Write a private run report with added, revised, unchanged, omitted, ambiguous, and failed counts; per-account observed date ranges; pagination results; source timestamps when present; and outstanding issues.

Start with a full re-fetch of the requested 2026 interval on each explicit sync. This bounded baseline catches older corrections that a simple last-date cursor would miss. It costs more calls than a recent-window-only strategy. Measure duration and call counts before introducing incremental windows or periodic historical reconciliation.

A run may finish `complete`, `partial`, `failed`, or `interrupted`. Here `complete` means all requested fetch units succeeded; it does not mean the bank supplied complete history. Completed account/windows remain usable if another fails. A restarted interrupted run retries unfinished units against their staged evidence; a new explicit sync rechecks the whole interval.

The catalog documents two requests per second with burst ten. Begin with sequential calls spaced at least one second apart, with no parallel bank requests. Honor `Retry-After` when present; otherwise use bounded exponential backoff with jitter for documented or observed throttling and transient transport/server errors. Allow three retries per request, then mark the unit failed. Repeated-page or non-advancing pagination detection and finite time/page bounds prevent loops; reaching a bound leaves the window incomplete.

Authentication/scope errors and payment-required responses stop the run and surface the actual problem. They must not trigger key rotation, purchases, reconnections, disconnections, force-syncs, or retries with unrelated credentials. A temporary key expiring is a sync failure, not evidence that a bank has no data. Credential persistence for unattended operation is a later scheduling requirement.

## 6. Public API contract and first implementation checkpoint

The [endpoint catalog](https://api.mcp.ai/api/openfinance/_endpoints) and [OpenAPI specification](https://api.mcp.ai/api/openfinance/_openapi), checked on 2026-09-16, document account selection, transaction date filters, pages/page sizes, and `compact`/`rich`/`raw` detail. The account detail/balance endpoints document batches of 1–50; transaction pages document 1–500 records.

Those public success schemas do not specify the transaction field names, status enum, pagination response shape, currency representation, balance timestamp fields, or date inclusivity. They do not guarantee complete 2026 history, stable transaction IDs, or immediate bank freshness. Marketing descriptions such as “real time” do not fill these gaps.

Implementation begins with a minimal read-only sample from the already authorized API, restricted to the requested dataset, to establish a versioned response adapter. Inspect account discovery, one bounded transaction window with pagination where available, and balance success/unavailable responses. Keep originals private; build synthetic fixtures reproducing only the necessary shapes.

The adapter must demonstrate source identity, account linkage, exact amount/currency handling, date interpretation, pagination termination, and error handling before a full import. An unknown shape fails that fetch unit explicitly. Do not invent fields or assume a short page proves completion without evidence. If pagination or identity cannot be established, stop full collection and report that specific limitation for review.

The baseline collector remains bank-data read-only. Its requests use the existing authorized MCP.AI endpoint and credential; provider reports containing financial evidence or external analysis uploads are not part of the research pipeline.

## 7. Validation and analytical interpretation

The first report is a data-quality profile, not a financial verdict. It includes:

- Inventory of observed accounts and unresolved local mappings.
- Per-account/month retrieval success, record counts, earliest/latest dates, and original currencies.
- Pagination completeness, field failures, missing identities, revisions, and possible replacement/duplicate records.
- Pending or unknown lifecycle states and differences between capture time and source as-of time.
- Balance observations with explicit kind, currency, and age.
- Possible transfers and card settlements requiring review, without treating proposals as confirmed classifications.

An empty successful result means “no records returned.” It does not establish no activity or complete historical coverage. Source availability, Operator review, and reconciliation remain separate dimensions, consistent with ADR 0008. Reports show their unresolved amounts/counts alongside any filtered totals rather than hiding them.

First analyses describe monthly inflows/outflows by account and currency, recurring descriptions, timing, merchant/category coverage, and cross-account movement candidates. They remain reproducible from a recorded set of accepted fetch units, the adapter version, and the annotation revision. A report records its cut-off so later syncs do not silently change what its findings refer to.

Cash movement is not automatically Income or Expense. Provider categories remain provider claims. Unknown lifecycle states are reported separately; pending records do not enter a settled-only view. Internal transfers and Credit Card Settlements must not become additional spending. Research cannot claim a reconciled balance from today's balance and a potentially incomplete transaction list.

The existing Household tracking policy governs any later MyFinance integration, including its specific treatment of debt repayment and refunds. This experiment does not silently redefine that policy. Confirmed account ownership and evidence are needed before combining accounts into a Household view.

## 8. Learning which features to build

Each finding records:

1. The question and reproducible query or analysis.
2. The evidence window, account coverage, and known limitations.
3. The result, distinguishing observation from hypothesis.
4. Any proposed feature, the decision it would help the Operator make, and a concrete success criterion.

A finding may yield a data-quality fix, another experiment, a useful saved query, a feature candidate, or no action. There is no obligation to turn every chart into a feature.

For example, recurring settlement ambiguity may justify a review queue; missing months may justify a coverage indicator; a frequently reused cash-flow query may justify an application report. These are hypotheses to test, not committed product requirements.

Raw findings containing personal financial information stay private. A feature promoted to a tracked spec or issue uses redacted or synthetic examples. Feature discovery does not itself authorize production-data writes or external LLM access.

## 9. Verification and completion criteria

Use synthetic provider fixtures to verify these behaviors before importing the full real dataset:

- Repeating a fetch creates no additional current transactions; changing a payload retains both versions.
- Identical legitimate purchases with different source IDs survive; missing IDs and ambiguous replacements are flagged.
- Pagination spans multiple pages; loops, interrupted pages, and partial inventory cannot report success or remove data.
- December/January boundaries, date-only fields, offset timestamps, unknown dates, and future-dated records respect the dataset scope.
- Decimal amounts and currencies round-trip exactly; missing balances and unsupported card balances remain unavailable.
- Provider rate limiting, credential expiry, and payment/scope errors produce the correct bounded outcome.
- A crash between artifact capture and SQLite publication leaves recoverable evidence and no false completion marker. Referenced artifacts are durable before commit; unreferenced captures are reported for recovery, not automatically deleted.
- Separate source bindings do not silently double-count overlapping account histories; source changes preserve and invalidate affected annotations.
- Analyses use a stable snapshot; local outputs remain ignored; logs contain no credentials, financial descriptions, amounts, or account/card identifiers.
- The collector refuses the live application DB. A research backup can be restored and its capture hashes verified.

The first research milestone is complete when all accessible initial accounts have explicit inventory and coverage results, the available 2026 dataset is collected or each gap is explained, a second sync demonstrates repeatability, and the quality profile plus at least one reproducible exploration produces a documented finding. No particular financial conclusion or new product feature is required.

## 10. Delivery sequence and later decisions

1. Validate response shapes and freeze the first adapter contract.
2. Build isolated capture/storage and prove identity, versioning, date boundaries, and safe publication with synthetic data.
3. Run a bounded real-data pilot, then collect the available 2026 dataset and repeat the sync.
4. Produce the quality profile, exploratory analyses, and feature discovery log.
5. Review evidence with the Operator and choose the next experiment or product change.

Scheduling, extra resource types, currency conversion, historical statement matching, production MyFinance integration, and Alfred access each require a follow-up decision informed by these results. They do not expand this first implementation by implication.

## References

- [Expense completeness operating model](2026-07-10-myfinance-expense-completeness-operating-model-design.md)
- [Private source records](../../adr/0007-private-source-record-handling.md)
- [Source coverage versus reconciliation](../../adr/0008-separate-source-coverage-from-reconciliation.md)
- [Live database protection](../../adr/0012-protect-the-live-financial-database.md)
- [Current database setup](../../../backend/app/database.py)
- [Current import models](../../../backend/app/models/imports.py)
- [Current import duplicate checks](../../../backend/app/imports/workflow.py)
- [Banco MCP endpoint catalog](https://api.mcp.ai/api/openfinance/_endpoints)
- [Banco MCP OpenAPI](https://api.mcp.ai/api/openfinance/_openapi)
