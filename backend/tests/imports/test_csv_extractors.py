from pathlib import Path

from app.imports.belfius_csv import BelfiusCsvExtractor
from app.imports.beobank_csv import BeobankCsvExtractor
from app.imports.nexo_csv import NexoCsvExtractor


def _write_csv(tmp_path: Path, filename: str, content: str, *, encoding: str = "utf-8") -> Path:
    file_path = tmp_path / filename
    file_path.write_text(content, encoding=encoding)
    return file_path


def test_belfius_csv_extractor_parses_rows_after_metadata_prefix(tmp_path):
    file_path = _write_csv(
        tmp_path,
        "belfius.csv",
        "\n".join(
            [
                "Boekingsdatum vanaf;01/02/2026",
                "Boekingsdatum tot en met;13/04/2026",
                "Bedrag vanaf;",
                "Bedrag tot en met;",
                "Rekeninguittrekselnummer vanaf;",
                "Rekeninguittrekselnummer tot en met;",
                "Mededeling;",
                "Naam tegenpartij bevat;",
                "Rekening tegenpartij;",
                "Laatste saldo;-140,40 EUR",
                "Datum/uur van het laatste saldo;11/04/2026 13:14:53",
                ";",
                "Rekening;Boekingsdatum;Rekeninguittrekselnummer;Transactienummer;Rekening tegenpartij;Naam tegenpartij bevat;Straat en nummer;Postcode en plaats;Transactie;Valutadatum;Bedrag;Devies;BIC;Landcode;Mededelingen",
                "BE46 0636 5194 6836;10/04/2026;00004;33;;;;;INTERESTEN : 01.01.2026 - 31.03.2026;01/04/2026;-3,59;EUR;;;INTERESTEN : 01.01.2026 - 31.03.2026",
            ]
        )
        + "\n",
    )

    evidence, result = BelfiusCsvExtractor().extract(file_path=file_path, session_id="12", attempt_number=1)

    assert result.extractor_id == "belfius_csv_v1"
    assert result.statement_metadata["account_number_hint"] == "BE46 0636 5194 6836"
    assert result.statement_metadata["statement_period_start"] == "2026-04-10"
    assert result.statement_metadata["statement_period_end"] == "2026-04-10"
    assert len(result.transactions) == 1
    assert result.transactions[0].transaction_date == "2026-04-10"
    assert result.transactions[0].signed_amount == -3.59
    assert result.transactions[0].currency == "EUR"
    assert result.transactions[0].proposed_transaction_type == "Expense"
    assert result.transactions[0].source_description == "INTERESTEN : 01.01.2026 - 31.03.2026"
    assert evidence.text_blocks[0]["page_number"] == 1
    assert evidence.snippets[0]["decision"] == "imported"


def test_beobank_csv_extractor_uses_numeric_filename_for_compact_export(tmp_path):
    file_path = _write_csv(
        tmp_path,
        "50212984548.csv",
        "\n".join(
            [
                "Datum;Waardedatum;Debet;Krediet;Omschrijving;Saldo",
                "03/01/2026;03/01/2026;-10,00;;Bancontact betaling Nationale Loterij;375,53",
            ]
        )
        + "\n",
        encoding="latin-1",
    )

    _, result = BeobankCsvExtractor().extract(file_path=file_path, session_id="22", attempt_number=1)

    assert result.extractor_id == "beobank_csv_v1"
    assert result.statement_metadata["account_number_hint"] == "50212984548"
    assert result.statement_metadata["statement_period_start"] == "2026-01-03"
    assert result.statement_metadata["statement_period_end"] == "2026-01-03"
    assert len(result.transactions) == 1
    assert result.transactions[0].transaction_date == "2026-01-03"
    assert result.transactions[0].signed_amount == -10.0
    assert result.transactions[0].proposed_transaction_type == "Expense"


def test_beobank_csv_extractor_keeps_empty_account_hint_for_debit_credit_export(tmp_path):
    file_path = _write_csv(
        tmp_path,
        "beobank-export.csv",
        "\n".join(
            [
                "Date;Debit;Credit;Message;Balance",
                "03/01/2026;10,00;;Card purchase;375,53",
                "04/01/2026;;25,00;Refund;400,53",
            ]
        )
        + "\n",
    )

    _, result = BeobankCsvExtractor().extract(file_path=file_path, session_id="23", attempt_number=1)

    assert result.statement_metadata["account_number_hint"] == ""
    assert result.statement_metadata["statement_period_start"] == "2026-01-03"
    assert result.statement_metadata["statement_period_end"] == "2026-01-04"
    assert [transaction.proposed_transaction_type for transaction in result.transactions] == [
        "Expense",
        "Income",
    ]


def test_nexo_csv_extractor_preserves_raw_currency_and_deterministic_proposals(tmp_path):
    file_path = _write_csv(
        tmp_path,
        "nexo.csv",
        "\n".join(
            [
                "Transaction,Type,Input Currency,Input Amount,Output Currency,Output Amount,USD Equivalent,Fee,Fee Currency,Details,Date / Time (UTC),normalizedDisplayDetails",
                "NXT_PURCHASE_1,Nexo Card Purchase,xUSD,-6.24000000,EUR,5.38000000,$6.24,-,-,approved / Albert Heijn 3143 | Gent | BEL,2026-03-25 17:19:21,approved / Albert Heijn 3143 | Gent | BEL",
                "NXT_FEE_1,Nexo Card Transaction Fee,xUSD,-0.16000000,xUSD,0.16000000,$0.16,-,-,approved / 2.0% Weekday FX Fee,2026-03-08 23:32:35,approved / 2.0% Weekday FX Fee",
                "NXT_CASHOUT_1,Transfer Out,USDC,-120.00000000,USDC,120.00000000,$120.00,-,-,approved / Bank transfer to BE55000000000001,2026-03-26 18:19:22,approved / Bank transfer to BE55000000000001",
            ]
        )
        + "\n",
    )

    evidence, result = NexoCsvExtractor().extract(file_path=file_path, session_id="42", attempt_number=3)

    assert result.statement_metadata["account_number_hint"] == "NEXO"
    assert result.statement_metadata["statement_period_start"] == "2026-03-08"
    assert result.statement_metadata["statement_period_end"] == "2026-03-26"
    assert [transaction.currency for transaction in result.transactions] == ["xUSD", "xUSD", "USDC"]
    assert [transaction.proposed_transaction_type for transaction in result.transactions] == [
        "Expense",
        "Expense",
        "Transfer",
    ]
    assert result.transactions[1].proposed_expense_category == "Financial Fees"
    assert result.transactions[2].proposed_transfer_category == "Internal Transfer"
    assert result.transactions[0].source_description == "Albert Heijn 3143 | Gent | BEL"
    assert result.transactions[2].source_locator == "csv:r4:NXT_CASHOUT_1"
    assert evidence.snippets[2]["decision"] == "imported"


def test_nexo_csv_extractor_skips_rejected_and_internal_rows_and_warns_on_ambiguous_transfer(tmp_path):
    file_path = _write_csv(
        tmp_path,
        "nexo-mixed.csv",
        "\n".join(
            [
                "Transaction,Type,Input Currency,Input Amount,Output Currency,Output Amount,USD Equivalent,Fee,Fee Currency,Details,Date / Time (UTC),normalizedDisplayDetails",
                "NXT_REJECTED_1,Nexo Card Purchase,xUSD,-6.24000000,EUR,5.38000000,$6.24,-,-,Rejected/Albert Heijn 3143 | Gent | BEL,2026-03-25 17:19:21,",
                "NXT_INTERNAL_1,Transfer Out,USDC,-33.45699600,USDC,33.45699600,$33.45,-,-,approved / Auto Transfer from Savings Wallet to Credit Line Wallet,2026-03-25 17:19:22,approved / Auto Transfer from Savings Wallet to Credit Line Wallet",
                "NXT_AMBIGUOUS_1,Transfer Out,USDC,-50.00000000,USDC,50.00000000,$50.00,-,-,approved / Wallet move to somewhere else,2026-03-26 18:19:22,approved / Wallet move to somewhere else",
                "NXT_CASHBACK_1,Cashback,NEXO,0.13428538,NEXO,0.13428538,$0.12,-,-,approved / Albert Heijn 3143 | Gent | BEL,2026-03-26 11:09:41,approved / Albert Heijn 3143 | Gent | BEL",
            ]
        )
        + "\n",
    )

    evidence, result = NexoCsvExtractor().extract(file_path=file_path, session_id="43", attempt_number=1)

    assert result.transactions == []
    assert any(issue.code == "ambiguous_nexo_transfer_out" and not issue.blocking for issue in result.issues)
    assert any(issue.code == "no_importable_nexo_rows" and issue.blocking for issue in result.issues)
    decisions = {snippet["transaction_id"]: snippet["decision"] for snippet in evidence.snippets}
    assert decisions["NXT_REJECTED_1"] == "skipped"
    assert decisions["NXT_INTERNAL_1"] == "skipped"
    assert decisions["NXT_CASHBACK_1"] == "skipped"
