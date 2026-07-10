# Household Finance

MyFinance gives one Operator trustworthy Household expense tracking. Its financial record distinguishes actual Expenses and Financial Costs from money movement, borrowing, and Credit Card Settlements.

## Language

**Operator**:
The sole person who operates MyFinance and curates its financial view.
_Avoid_: User, customer, owner

**Household**:
The Operator and spouse whose selected financial activity is measured together.
_Avoid_: Users, tenants

**Financial Perimeter**:
The set of financial accounts whose activity is consolidated as one Household view. Movement between two accounts inside this perimeter does not leave the Household.
_Avoid_: Account list, imported accounts

**Consolidated Financial Record**:
A trusted, normalized, traceable representation of activity inside the Financial Perimeter across Financial Institutions, account holders, countries, and currencies, in which money movements and their financial costs are distinct.
_Avoid_: Dashboard data, analytics cache, transaction database

**Financial Institution**:
An external organization that holds an account or issues financial Source Records, including a bank, card issuer, payment platform, or crypto platform.
_Avoid_: Provider, bank when the institution is not a bank

**Source Record**:
Evidence received from a Financial Institution from which financial facts originate, such as a statement row or statement document.
_Avoid_: Input, raw data

**Institution Profile**:
Confirmed knowledge about how a specific Financial Institution and source format express accounts, amounts, signs, currencies, descriptions, and financial meaning.
_Avoid_: Global model, provider configuration, parser

**Statement Stream**:
A recurring sequence of Source Records for one financial account or card product and one source format, with an expected cadence.
_Avoid_: Bank, folder, account

**Statement Period**:
The actual date interval covered by a statement Source Record, independent of how that record is filed by month.
_Avoid_: Calendar month, download month, folder month

**Statement Slot**:
The expected monthly position of a Source Record within a Statement Stream, labeled by the month in which its Statement Period ends.
_Avoid_: Calendar month, transaction month, download month

**Coverage Calendar**:
The per-Statement-Stream record of which Statement Slots are expected, not yet due, received, reviewed, complete, unresolved, or confirmed to have no activity.
_Avoid_: Folder listing, import history

**No-Activity Slot**:
A Statement Slot for which the Financial Institution produced no financial activity and may therefore produce no Source Record. It requires institution evidence or Operator confirmation rather than inference from an empty folder.
_Avoid_: Empty month, missing file

**Statement Schedule**:
The Operator-maintained closing cadence and normal availability delay for a Statement Stream, recorded from information the Operator obtains from the Financial Institution.
_Avoid_: Calendar month, import schedule

**Unresolved Slot**:
A Statement Slot whose expected availability has passed without a Source Record or confirmed no-activity reason.
_Avoid_: Empty month, missing transaction

**Coverage Start**:
The first Statement Slot from which a Statement Stream is expected to have complete monthly coverage. Earlier Source Records may be imported without creating unresolved coverage obligations.
_Avoid_: Account opening date, earliest transaction, first imported file

**Source Complete**:
A Statement Slot state meaning every expected Source Record is present or the slot is confirmed to have no activity. It does not assert that extracted financial data is correct.
_Avoid_: Reconciled, imported, file exists

**Reconciliation**:
Verification that Financial Events reproduce the available balances and control totals in their Source Records, with any difference explicitly explained.
_Avoid_: Import success, review, file received

**Reconciled Slot**:
A Source Complete Statement Slot whose available financial evidence agrees with the Consolidated Financial Record.
_Avoid_: Complete month, reviewed file

**Reviewed Slot**:
A Source Complete Statement Slot whose extracted Financial Events the Operator has approved. It may remain unreconciled when its Source Records lack Control Evidence.
_Avoid_: Reconciled Slot, imported file

**Control Evidence**:
A Financial Institution balance or declared total used to verify that extracted Financial Events faithfully reproduce a Source Record.
_Avoid_: File presence, successful parsing, transaction count

**Working View**:
A reporting view derived from Financial Events in Reviewed Slots, including unreconciled data while displaying its provisional status and coverage gaps.
_Avoid_: Final report, verified total

**Verified View**:
A reporting view derived only from Financial Events in Reconciled Slots.
_Avoid_: Working total, reviewed data

**Expense**:
A reviewed Financial Event counted as Household spending. Internal Transfers, Credit Card Settlements, borrowed funds, and exchanges of one Asset for another are not Expenses; cash withdrawals and loan payments may be Expenses under the Household's practical tracking policy.
_Avoid_: Debit, card charge, money out

**Expense Coverage**:
The degree to which every Household Expense in a target period is represented by reviewed Source Records or other Operator-confirmed evidence.
_Avoid_: Transaction count, file coverage, estimated spending

**Classification Proposal**:
A non-authoritative suggested transaction type and category produced from local similarity or a sanitized external classifier request. It becomes part of the Consolidated Financial Record only after Operator approval.
_Avoid_: Classification, automatic fact, model answer

**Transfer**:
A movement of existing value between Asset Accounts inside the Financial Perimeter. It changes where Household money is held without being Income or an expense, although Financial Costs may accompany it.
_Avoid_: Expense, payment

**Financial Cost**:
An economic loss attributable to financial activity, such as a provider fee or exchange-rate loss, distinct from the principal moved.
_Avoid_: Transfer amount, principal

**Explicit Cost**:
A Financial Cost stated by a Financial Institution, including a fee, tax, interest charge, penalty, or overdraft charge.
_Avoid_: Principal, exchange-rate difference

**Exchange-Rate Cost**:
The value lost because an applied currency-conversion rate is worse than an independent Reference Rate, calculated without counting Explicit Costs twice.
_Avoid_: Currency conversion, market movement, explicit fee

**Reference Rate**:
The independent daily ECB exchange rate used to benchmark a currency conversion, retained with its source and date. Its date follows the conversion date, then value date, then booking date, using the latest earlier published rate when necessary.
_Avoid_: Applied rate, provider quote, guaranteed market rate

**Applied Rate**:
The actual effective exchange rate charged by a Financial Institution, taken from a Source Record or derived from the source and destination amounts after separating Explicit Costs.
_Avoid_: Reference Rate, assumed market rate

**Realized Cost**:
The combined Explicit Costs and Exchange-Rate Costs attributable to a Financial Event or Movement Chain.
_Avoid_: Principal, projected cost, opportunity cost

**Cost Pending**:
A Movement Chain state meaning Realized Cost cannot yet be finalized because neither a documented Applied Rate nor sufficient linked source and destination amounts are available.
_Avoid_: Zero cost, unknown forever, estimated cost

**Original Amount**:
The amount and currency stated by a Source Record, preserved without conversion or replacement.
_Avoid_: Display amount, normalized amount

**Reporting Currency**:
The currency selected to compare and aggregate Original Amounts without changing them. EUR is the Household default, with BRL and USD available as alternatives.
_Avoid_: Source currency, account currency

**Income**:
Value received from outside the Financial Perimeter without a matching obligation to repay. Transfers and borrowed funds are not Income.
_Avoid_: Account credit, deposit, inflow

**Asset Account**:
A financial account holding value that belongs to the Household, such as a bank or Wise balance.
_Avoid_: Positive account, debit account

**Liability Account**:
A financial account representing value the Household must repay, such as a credit card or overdraft.
_Avoid_: Negative account, expense account

**Credit Draw**:
A financing event that increases an Asset Account and a Liability Account by equivalent economic value. It is not Income.
_Avoid_: Income, deposit, transfer

**Debt Repayment**:
A payment toward a debt obligation. It may be an Expense when the liability is outside the Financial Perimeter; when the liability is tracked, principal reduces that liability while interest and fees remain Financial Costs.
_Avoid_: Credit Card Settlement, interest charge

**Credit Card Purchase**:
An itemized card charge recognized once as an Expense in the category that describes what was bought.
_Avoid_: Credit Card Settlement, card payment

**Credit Card Settlement**:
A Transfer from an Asset Account that pays a credit-card statement or balance. It is not an Expense because the underlying Credit Card Purchases were already recognized individually.
_Avoid_: Credit Card Purchase, loan payment, Expense

**Card Statement Reconciliation**:
Verification that a card statement's itemized purchases, fees, credits, amount due, and one or more settlement payments agree without counting those payments as Expenses.
_Avoid_: Purchase classification, payment allocation

**Settlement Coverage**:
The comparison between a card statement's amount due and all Credit Card Settlements applied to it, expressed as unpaid, partially settled, fully settled, or overpaid with the remaining difference.
_Avoid_: Expense total, purchase allocation

**Net Financial Position**:
The value of the Household's financial assets minus its financial liabilities.
_Avoid_: Account balance, cash balance, income

**Financial Event**:
A single economically meaningful occurrence in the Consolidated Financial Record, such as Income, a Transfer, a Credit Draw, a Debt Repayment, or a Financial Cost.
_Avoid_: Transaction row, source row, database record

**Movement Chain**:
A connected set of Financial Events explaining how value was funded, moved, converted, costed, and settled across the Financial Perimeter. A Movement Chain may branch or merge through Event Allocations and may be complete, incomplete, or uncertain according to its available Source Records.
_Avoid_: Transfer Chain, transaction group

**Event Allocation**:
A portion of one Financial Event connected to another within a Movement Chain. Allocations represent splits, merges, and partial settlement without duplicating Source Records or claiming unsupported precision.
_Avoid_: Split transaction, copied row
