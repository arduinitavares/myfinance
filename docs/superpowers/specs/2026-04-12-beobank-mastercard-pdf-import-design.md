# Beobank Mastercard PDF Import Design

Date: 2026-04-12
Status: Drafted for review
Scope: deterministic import support for text-selectable Beobank Mastercard statement PDFs only

## Goals

- Import itemized Beobank Mastercard statement transactions from PDF.
- Reuse the existing statement-import pipeline and artifact trail.
- Parse only the detailed transaction table, not statement summaries.
- Keep the import review-first workflow: extract, review, then commit.
- Fail closed when the PDF is scanned, password-protected, or layout-incompatible.

## Non-Goals

- OCR support in v1.
- AI-based extraction in the primary path.
- Importing summary balances or payment totals from page 1.
- Supporting Beobank account-statement PDFs in this slice.
- Supporting other Mastercard layouts or other banks in this slice.

## High-Level Decision

The first implementation will use a deterministic parser, not AI.

Reasoning:

- The Beobank Mastercard PDF has a usable text layer.
- The transaction pages expose a stable 3-column table: `Datum`, `Beschrijving`, `Bedrag (in EUR)`.
- Deterministic parsing is cheaper, easier to test, and safer than an LLM for a monthly import flow.

AI remains a possible later fallback for rejected PDFs, but it is out of scope for this first slice.

## Shared Foundation Alignment

This slice does not change the shared rule that the pipeline routes by `strategy_key` only.

The alignment for `pdf_statement` is:

- pipeline selects `PdfStatementExtractor` because `strategy_key = pdf_statement`
- `PdfStatementExtractor` owns an ordered PDF sub-extractor chain
- this slice adds `BeobankMastercardPdfExtractor` as a deterministic sub-extractor in that chain
- later AI fallback may be added behind it without changing pipeline routing

For deterministic Beobank Mastercard attempts:

- `extractor_id` must be `beobank_mastercard_pdf_v1`
- `evidence/raw.json` must be present
- `normalized/extraction_result.json` must be present
- `ai/request.json` and `ai/response.json` must be absent

This makes the deterministic path compatible with the accepted shared import architecture instead of replacing it.

## Source Format Assumptions

The accepted Beobank Mastercard PDF format has these characteristics:

- Page 1 is always a summary page and must never be used for transaction import.
- Transaction details start on page 2.
- The document may have any number of pages after page 1.
- Transaction pages contain:
  - section title `Uw transacties`
  - column headers `Datum`, `Beschrijving`, `Bedrag`
- A card header line such as `Kaart ARDUINI TAVARES ALEXANDRE - 5468XXXXXXXX9159` may appear and must be ignored.
- Foreign-currency helper lines may appear under a purchase, such as:
  - `117,05 BRL WISSELKOERS 0.155404`
- Fee lines may appear as their own rows, such as:
  - `WISSELKOSTEN`
- Accepted language for v1 is Dutch only. If the document does not expose the Dutch markers and table headers described here, the extractor must reject it as unsupported layout.

## Card Section Handling

Card header lines are not importable transactions, but they remain structural markers.

Rules:

- repeated occurrences of the same masked `Kaart ...` header are allowed and ignored as rows
- the masked card number from that header must populate `card_number_hint` when available
- if more than one distinct masked card header appears in the same PDF, the extractor must fail with blocking issue code `multi_card_not_supported`

This v1 slice therefore accepts only single-card statements even if the layout could theoretically contain multiple card sections.

## Extraction Scope

The importer will parse only the transaction table rows from pages 2 through the end of the document.

The parser must inspect every page from page 2 onward, but extract rows only from pages that satisfy the transaction-table shape:

- page contains `Uw transacties`
- page contains the table header
- page contains at least one valid dated row with an amount

Pages after page 1 that do not match this shape are ignored rather than guessed.

## Page Qualification and Line Classes

After page 1 is skipped, each page must be classified as either:

- `transaction_page`
- `non_transaction_page`

A page is a `transaction_page` only if extracted text contains:

- `Uw transacties`
- header tokens `Datum`, `Beschrijving`, and `Bedrag` before the first parsed row
- at least one valid row start

Within a `transaction_page`, every non-empty line in the table body must classify as exactly one of:

- `card_header`
- `table_header`
- `row_start`
- `continuation`
- `fx_helper`
- `page_footer_noise`

`WISSELKOSTEN` is a special case of `row_start`, not a separate helper line.

Any non-empty table-body line that cannot be classified into one of those classes is a blocking issue `unclassifiable_table_line`.

## Imported Data Contract

Only these table columns are authoritative for row creation:

- `Datum`
- `Beschrijving`
- `Bedrag (in EUR)`

Each imported transaction row must produce:

- `transaction_date`
- `source_description`
- `signed_amount`
- `currency = "EUR"`
- `debit_credit`
- `source_locator`

Standard import metadata continues to flow through `ExtractionResult` and draft tables.

## Explicit Ignore Rules

The parser must ignore:

- all content from page 1
- summary fields such as:
  - `Vorig saldo`
  - `Uitgaven`
  - `Andere debiteringen`
  - `Andere crediteringen`
  - `Geregistreerde betalingen`
  - `Opgebruikt bedrag`
- card section headers like `Kaart ...`
- FX helper lines like `117,05 BRL WISSELKOERS ...`
- informational or marketing text outside the transaction table

Ignoring these fields is intentional. They are statement summaries, not itemized transactions.

## Row Parsing Rules

### New transaction rows

A new transaction row begins when the parser finds a line with:

- a leading date in `dd/MM/yyyy`
- a description region
- a right-side EUR amount

For v1, a row start is valid only if the parsed amount token matches Belgian numeric format:

- `12,34`
- `1.234,56`
- `-12,34`
- `-1.234,56`

Any other amount shape is a blocking `malformed_row`.

### Multiline descriptions

If a line does not start a new dated row and does not match an ignore rule, it is treated as a continuation of the previous transaction description.

Continuation lines are appended to the previous row with normalized whitespace.

If a continuation-like line appears before the first parsed row on a transaction page, it is a blocking issue `orphan_continuation`.

### FX helper lines

Lines containing original-currency hints such as `BRL WISSELKOERS` or `USD WISSELKOERS` are attached to neither description nor amount. They are ignored for v1.

### Fee rows

If `WISSELKOSTEN` appears with its own EUR amount in the transaction table, it becomes its own imported transaction row.

### Negative and positive sign handling

The statement table visually expresses most purchase amounts as unsigned positive numbers even when they are debit spending. The importer must convert imported amounts into signed amounts using statement semantics:

- any parsed amount token without an explicit leading minus sign imports as:
  - `signed_amount < 0`
  - `debit_credit = "debit"`
- any parsed amount token with an explicit leading minus sign imports as:
  - `signed_amount > 0`
  - `debit_credit = "credit"`

This rule applies only inside the Mastercard transaction table, not to other importers.

## Source Locator Contract

Every extracted transaction row and every issue tied to a table line must use the same stable locator format:

- `pdf:p{page}:l{start_line}`
- `pdf:p{page}:l{start_line}-{end_line}` for multiline descriptions

Examples:

- `pdf:p2:l11`
- `pdf:p3:l18-l20`

This locator is the only accepted `source_locator` syntax for this slice.

## Recognition and Validation

The pipeline keeps the generic `pdf_statement` detector.

The Beobank-specific extractor is responsible for validating that the uploaded PDF is the expected Mastercard layout. It must confirm page-1 markers like:

- `Uittreksel van uw kredietkaart`
- `BEOBANK`
- `MASTERCARD`

If those markers are missing, the extractor must reject the file as not matching this format.

## Failure Handling

The importer must fail closed in these cases:

- PDF is password-protected
- PDF has no usable text layer
- PDF appears scanned/image-only
- PDF does not match Beobank Mastercard layout
- Pages 2..N contain no valid transaction rows

The failure response must be explicit and reviewable. Do not guess from image content in v1.

Blocking issue codes for this slice are:

- `password_protected_pdf`
- `image_only_pdf`
- `unsupported_beobank_mastercard_layout`
- `multi_card_not_supported`
- `empty_transaction_page`
- `orphan_continuation`
- `malformed_row`
- `unclassifiable_table_line`

Partial parsing rules are strict:

- if a transaction page is detected and any non-ignored line cannot be classified, extraction fails
- if a transaction page is detected and zero valid rows remain after parsing, extraction fails with `empty_transaction_page`
- if a row start has an unparsable date or amount, extraction fails with `malformed_row`
- if a continuation appears before any row start on that page, extraction fails with `orphan_continuation`

Warning-only issues are allowed only for non-authoritative metadata extraction. A table-row parsing failure is never warning-only in this slice.

Failed sessions must not enter `awaiting_review`.

## Artifact and Audit Behavior

This slice reuses the existing import artifact layout.

For each extraction attempt, store:

- original PDF under `original/`
- extracted page text in raw evidence
- normalized extraction result
- import issues generated during parsing

The raw evidence must retain enough page-level context to debug parser drift later.

## Pipeline Integration

This feature adds a format-specific extractor to the existing import foundation.

Expected flow:

`upload -> detect pdf_statement -> validate as Beobank Mastercard -> extract page text -> parse transaction pages -> build ExtractionResult -> review -> commit`

This slice does not change the CSV import path.

This slice does not bypass review.

## Review Expectations

This slice keeps the shared review UI contract.

The review screen must still show:

- statement summary metadata when available
- issue summary
- transaction draft table
- evidence panel with raw PDF text snippets for selected rows or issues
- approval / rejection controls

The editable transaction surface for this slice is limited to the extracted draft rows:

- transaction date
- description
- signed EUR amount

Blocking issues prevent approval. Warning-only issues remain visible.

Page-1 summary fields are never presented as importable rows.

## Testing Strategy

Tests must not use private bank PDFs committed into the repo.

Use sanitized fixtures derived from the format shape, not the user’s real statements.

### Unit tests

- recognizes Beobank Mastercard page-1 markers
- rejects PDFs with no usable text layer
- rejects multi-card PDFs
- ignores page 1 completely
- parses transactions beginning on page 2
- parses multiple transaction pages
- ignores repeated table headers on later pages
- ignores `Kaart ...` header rows
- ignores FX helper lines
- keeps `WISSELKOSTEN` as its own row when present
- converts negative statement rows into positive imported amounts
- converts normal purchase rows into negative imported amounts
- joins multiline descriptions correctly
- emits stable `source_locator` values
- fails on orphan continuation and other unclassifiable table lines
- preserves line-wrap and spacing in sanitized text fixtures

### Integration tests

- upload valid Beobank Mastercard PDF fixture into import pipeline
- confirm detection remains `pdf_statement`
- confirm deterministic extractor is selected inside `PdfStatementExtractor`
- confirm extractor produces expected draft rows
- confirm no page-1 summary rows appear in output
- confirm malformed transaction-page input fails extraction and never reaches `awaiting_review`

## Out of Scope Follow-Ups

These are intentionally deferred:

- OCR fallback for scanned PDFs
- AI fallback for unsupported PDF layouts
- parsing and storing original foreign-currency helper values
- importing Beobank bank-account PDFs
- reconciling card purchases against bank-side settlement transactions

## Acceptance Criteria

This slice is complete when:

- a text-selectable Beobank Mastercard PDF can be uploaded through the import pipeline
- page 1 is ignored entirely
- only itemized transaction rows from pages 2..N are extracted
- `WISSELKOSTEN` rows are preserved as separate rows
- FX helper lines are ignored
- extracted draft rows are available for review before commit, with issue summary and evidence panel still visible
- scanned/password/incompatible PDFs fail explicitly instead of guessing
