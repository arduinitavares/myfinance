import logging
from pathlib import Path
import pandas as pd
from typing import List, Callable, Dict, Optional, Set, Tuple
from ..schemas.transaction import TransactionCreate
from ..models.transaction import TransactionType

logger = logging.getLogger(__name__)

class CSVParser:
    # ----------------------------------------------------------------------------------
    # Registry utilities
    # ----------------------------------------------------------------------------------
    # Mapping of bank identifier -> {"headers": Set[str], "parser": Callable[[str], List[TransactionCreate]]}
    _bank_parsers: Dict[str, Dict[str, Callable]] = {}

    @classmethod
    def register_bank_parser(
        cls,
        name: str,
        headers: Set[str],
        parser_func: Callable[[str, Optional[str], int], List[TransactionCreate]],
    ) -> None:
        """Register a new CSV parser for a specific bank.

        Parameters
        ----------
        name: str
            Identifier used for the bank (e.g. "ING", "KBC").
        headers: Set[str]
            Column names that must be present in the CSV file for this parser
            to be selected.
        parser_func: Callable[[str], List[TransactionCreate]]
            Function that receives the *file path* to a CSV exported from the
            bank and returns a list of ``TransactionCreate`` objects.
        """
        cls._bank_parsers[name] = {"headers": set(headers), "parser": parser_func}

    @staticmethod
    def match_bank_format(headers: List[str]) -> Optional[str]:
        headers_set = {header.strip() for header in headers if str(header).strip()}

        for bank_name, info in CSVParser._bank_parsers.items():
            if info["headers"].issubset(headers_set):
                return bank_name

        return None

    @staticmethod
    def detect_bank_format(headers: List[str]) -> str:
        """Return the identifier of the bank whose headers match ``headers``.

        The method iterates over all bank parsers registered via
        :py:meth:`register_bank_parser` and returns the first one whose
        declared header set is a subset of the provided ``headers`` list.
        """
        headers_set = {header.strip() for header in headers if str(header).strip()}
        logger.info(f"Detecting bank format. Available headers: {headers_set}")

        bank_name = CSVParser.match_bank_format(headers)
        if bank_name:
            logger.info(f"Bank format detected: {bank_name}")
            return bank_name

        logger.error(f"No matching bank format found. Headers: {headers_set}")
        raise ValueError("Unsupported CSV format")

    @staticmethod
    def convert_amount(amount_str: str) -> float:
        """Convert string amount to float, handling different number formats"""
        # Remove any whitespace
        amount_str = str(amount_str).strip()
        # Replace comma with period for decimal point
        amount_str = amount_str.replace(',', '.')
        return float(amount_str)

    @staticmethod
    def convert_date(date_str: str) -> str:
        """Convert date from DD/MM/YYYY to YYYY-MM-DD format"""
        try:
            day, month, year = date_str.split('/')
            return f"{year}-{month}-{day}"
        except ValueError:
            return date_str  # Return as-is if already in correct format

    @staticmethod
    def parse_ing_csv(file_path: str, source_filename: Optional[str] = None, header_row_index: int = 0) -> List[TransactionCreate]:
        df = CSVParser.read_csv_with_fallback(file_path, skiprows=header_row_index)
        transactions = []
        
        for _, row in df.iterrows():
            amount = CSVParser.convert_amount(row["Amount"])
            transaction = TransactionCreate(
                account_number=row["Account Number"],
                transaction_date=CSVParser.convert_date(row["Booking date"]),
                amount=amount,
                currency=row["Currency"],
                description=row["Description"],
                counterparty_account=row["Counterparty account"]
                    if pd.notna(row["Counterparty account"]) else None,
                transaction_type=TransactionType.INCOME if amount > 0 else TransactionType.EXPENSE,
                source_bank="ING"
            )
            transactions.append(transaction)
            
        return transactions

    @staticmethod
    def parse_kbc_csv(file_path: str, source_filename: Optional[str] = None, header_row_index: int = 0) -> List[TransactionCreate]:
        df = CSVParser.read_csv_with_fallback(file_path, skiprows=header_row_index)
        transactions = []
        
        for _, row in df.iterrows():
            amount = CSVParser.convert_amount(row["Amount"])
            transaction = TransactionCreate(
                account_number=row["Account number"],
                transaction_date=CSVParser.convert_date(row["Date"]),
                amount=amount,
                currency=row["Currency"],
                description=row["Description"],
                counterparty_name=row["Counterparty name"]
                    if pd.notna(row["Counterparty name"]) else None,
                counterparty_account=row["counterparty's account number"]
                    if pd.notna(row["counterparty's account number"]) else None,
                transaction_type=TransactionType.INCOME if amount > 0 else TransactionType.EXPENSE,
                source_bank="KBC"
            )
            transactions.append(transaction)
            
        return transactions

    @staticmethod
    def parse_beobank_csv(file_path: str, source_filename: Optional[str] = None, header_row_index: int = 0) -> List[TransactionCreate]:
        logger.info(f"Starting Beobank CSV parsing for file: {file_path}")
        df = CSVParser.read_csv_with_fallback(file_path, skiprows=header_row_index)
        logger.info(f"CSV loaded successfully. Columns: {df.columns.tolist()}")
        logger.info(f"DataFrame shape: {df.shape}")
        transactions = []
        
        for idx, row in df.iterrows():
            logger.debug(f"Processing row {idx}: {row.to_dict()}")
            # Determine transaction type and amount
            debit = row.get("Debit", "")
            credit = row.get("Credit", "")
            
            logger.debug(f"Row {idx} - Debit: {debit}, Credit: {credit}")
            
            if pd.notna(debit) and str(debit).strip():
                amount = -CSVParser.convert_amount(debit)  # Debit is negative
                transaction_type = TransactionType.EXPENSE
                logger.debug(f"Row {idx} - Debit transaction: amount={amount}")
            elif pd.notna(credit) and str(credit).strip():
                amount = CSVParser.convert_amount(credit)  # Credit is positive
                transaction_type = TransactionType.INCOME
                logger.debug(f"Row {idx} - Credit transaction: amount={amount}")
            else:
                logger.debug(f"Row {idx} - Skipping row with no amount")
                continue  # Skip rows with no amount
            
            try:
                transaction = TransactionCreate(
                    account_number="",  # Beobank CSV doesn't include account number
                    transaction_date=CSVParser.convert_date(row["Date"]),
                    amount=amount,
                    currency="EUR",  # Beobank uses EUR by default
                    description=row["Message"],
                    counterparty_account=None,
                    transaction_type=transaction_type,
                    source_bank="Beobank"
                )
                transactions.append(transaction)
                logger.debug(f"Row {idx} - Transaction created successfully")
            except Exception as e:
                logger.error(f"Row {idx} - Error creating transaction: {e}", exc_info=True)
                raise
            
        logger.info(f"Beobank CSV parsing completed. Total transactions: {len(transactions)}")
        return transactions

    @staticmethod
    def infer_account_number_from_filename(source_filename: Optional[str]) -> str:
        if not source_filename:
            return ""

        stem = Path(source_filename).stem
        return stem if stem.isdigit() else ""

    @staticmethod
    def parse_beobank_compact_csv(
        file_path: str,
        source_filename: Optional[str] = None,
        header_row_index: int = 0,
    ) -> List[TransactionCreate]:
        df = CSVParser.read_csv_with_fallback(file_path, skiprows=header_row_index)
        transactions = []
        account_number = CSVParser.infer_account_number_from_filename(source_filename)

        for _, row in df.iterrows():
            debit = row.get("Debet", "")
            credit = row.get("Krediet", "")

            if pd.notna(debit) and str(debit).strip():
                amount = CSVParser.convert_amount(debit)
                if amount > 0:
                    amount = -amount
                transaction_type = TransactionType.EXPENSE
            elif pd.notna(credit) and str(credit).strip():
                amount = CSVParser.convert_amount(credit)
                transaction_type = TransactionType.INCOME
            else:
                continue

            transaction = TransactionCreate(
                account_number=account_number,
                transaction_date=CSVParser.convert_date(row["Datum"]),
                amount=amount,
                currency="EUR",
                description=row["Omschrijving"],
                counterparty_account=None,
                transaction_type=transaction_type,
                source_bank="Beobank",
            )
            transactions.append(transaction)

        return transactions

    @staticmethod
    def parse_belfius_csv(
        file_path: str,
        source_filename: Optional[str] = None,
        header_row_index: int = 0,
    ) -> List[TransactionCreate]:
        df = CSVParser.read_csv_with_fallback(file_path, skiprows=header_row_index)
        transactions = []

        for _, row in df.iterrows():
            amount = CSVParser.convert_amount(row["Bedrag"])
            description = row["Mededelingen"] if pd.notna(row["Mededelingen"]) and str(row["Mededelingen"]).strip() else row["Transactie"]

            transaction = TransactionCreate(
                account_number=row["Rekening"] if pd.notna(row["Rekening"]) else CSVParser.infer_account_number_from_filename(source_filename),
                transaction_date=CSVParser.convert_date(row["Boekingsdatum"]),
                amount=amount,
                currency=row["Devies"] if pd.notna(row["Devies"]) and str(row["Devies"]).strip() else "EUR",
                description=description,
                counterparty_name=row["Naam tegenpartij bevat"] if pd.notna(row["Naam tegenpartij bevat"]) and str(row["Naam tegenpartij bevat"]).strip() else None,
                counterparty_account=row["Rekening tegenpartij"] if pd.notna(row["Rekening tegenpartij"]) and str(row["Rekening tegenpartij"]).strip() else None,
                transaction_type=TransactionType.INCOME if amount > 0 else TransactionType.EXPENSE,
                source_bank="Belfius",
            )
            transactions.append(transaction)

        return transactions

    @staticmethod
    def read_text_lines_with_fallback(file_path: str) -> Tuple[List[str], str]:
        encodings = ['utf-8', 'latin1', 'iso-8859-1']
        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as csv_file:
                    return csv_file.read().splitlines(), encoding
            except UnicodeDecodeError as e:
                logger.warning(f"Failed to read CSV text with encoding {encoding}: {e}")

        logger.error("Failed to read CSV text with all attempted encodings")
        raise ValueError("Failed to read CSV with all attempted encodings")

    @staticmethod
    def detect_bank_format_from_file(file_path: str) -> Tuple[str, int]:
        lines, encoding = CSVParser.read_text_lines_with_fallback(file_path)
        logger.info(f"Scanning CSV header candidates using encoding: {encoding}")

        for index, line in enumerate(lines):
            headers = [part.strip() for part in line.split(';')]
            bank_name = CSVParser.match_bank_format(headers)
            if bank_name:
                logger.info(f"Bank format detected: {bank_name} at line {index + 1}")
                return bank_name, index

        logger.error("No matching bank format found while scanning file")
        raise ValueError("Unsupported CSV format")

    @staticmethod
    def read_csv_with_fallback(file_path: str, *, skiprows: int = 0) -> pd.DataFrame:
        logger.info(f"Reading CSV file: {file_path}")
        encodings = ['utf-8', 'latin1', 'iso-8859-1']
        for encoding in encodings:
            try:
                logger.info(f"Attempting to read with encoding: {encoding}")
                df = pd.read_csv(file_path, sep=';', encoding=encoding, skiprows=skiprows)
                logger.info(f"Successfully read CSV with encoding {encoding}")
                return df
            except UnicodeDecodeError as e:
                logger.warning(f"Failed to read CSV with encoding {encoding}: {e}")
        logger.error("Failed to read CSV with all attempted encodings")
        raise ValueError("Failed to read CSV with all attempted encodings")

    # ------------------------------------------------------------------------------
    # Generic parsing entry-point
    # ------------------------------------------------------------------------------
    @staticmethod
    def parse_csv(file_path: str, source_filename: Optional[str] = None) -> List[TransactionCreate]:
        """Parse a CSV file exported from any supported bank.

        This is a convenience wrapper that reads the file once to inspect its
        headers, determines the correct parser by calling
        :py:meth:`detect_bank_format`, and then delegates the actual parsing
        work to the bank-specific parser function registered in
        ``_bank_parsers``.
        """
        logger.info(f"Starting CSV parsing for: {file_path}")
        try:
            bank_name, header_row_index = CSVParser.detect_bank_format_from_file(file_path)
            logger.info(f"Using parser for bank: {bank_name}")
            parser_func = CSVParser._bank_parsers[bank_name]["parser"]
            result = parser_func(file_path, source_filename, header_row_index)
            logger.info(f"CSV parsing completed successfully. Total transactions: {len(result)}")
            return result
        except Exception as e:
            logger.error(f"Error parsing CSV: {e}", exc_info=True)
            raise

# ----------------------------------------------------------------------------------
# Register built-in parsers so they are available immediately on import
# ----------------------------------------------------------------------------------

CSVParser.register_bank_parser(
    "ING",
    {"Account Number", "Account Name", "Counterparty account", "Booking date"},
    CSVParser.parse_ing_csv,
)

CSVParser.register_bank_parser(
    "KBC",
    {"Account number", "Heading", "Name", "Currency"},
    CSVParser.parse_kbc_csv,
)

CSVParser.register_bank_parser(
    "Beobank",
    {"Date", "Debit", "Credit", "Message", "Balance"},
    CSVParser.parse_beobank_csv,
)

CSVParser.register_bank_parser(
    "Beobank Compact",
    {"Datum", "Waardedatum", "Debet", "Krediet", "Omschrijving", "Saldo"},
    CSVParser.parse_beobank_compact_csv,
)

CSVParser.register_bank_parser(
    "Belfius",
    {
        "Rekening",
        "Boekingsdatum",
        "Rekeninguittrekselnummer",
        "Transactienummer",
        "Rekening tegenpartij",
        "Naam tegenpartij bevat",
        "Transactie",
        "Valutadatum",
        "Bedrag",
        "Devies",
        "Mededelingen",
    },
    CSVParser.parse_belfius_csv,
)
