from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session
from sqlalchemy import func
import logging

from ..database import get_db
from ..models.transaction import (
    Transaction,
    ExpenseCategory,
    IncomeCategory,
    TransactionType,
    TransferCategory,
)
from ..models.anomaly import TransactionAnomaly
from ..schemas import transaction as schemas
from ..services.currency_conversion import CurrencyConversionService
from ..services.reporting_currency import get_reporting_currency
from ..services.statistics_service import StatisticsService
from ..services.anomaly_detection_service import AnomalyDetectionService
from ..services.classification_commit_service import commit_category_change
from datetime import datetime

# Set up logging
logger = logging.getLogger(__name__)

# Create router
router = APIRouter(
    prefix="/transactions",
    tags=["transactions"]
)

# Define sort field mapping
SORT_FIELD_MAPPING = {
    'date': 'transaction_date',
    'description': 'description',
    'amount': 'amount',
    'type': 'transaction_type'
}


def _serialize_transaction_for_response(
    transaction: Transaction,
    *,
    conversion_service: CurrencyConversionService,
    reporting_currency: str,
):
    return schemas.build_transaction_response_payload_for_reporting_currency(
        transaction,
        conversion_service=conversion_service,
        reporting_currency=reporting_currency,
    )

@router.get("/", response_model=schemas.TransactionPage)
def get_transactions(
    db: Session = Depends(get_db),
    reporting_currency: str = Depends(get_reporting_currency),
    page: int = Query(1, gt=0),
    page_size: int = Query(10, gt=0, le=100),
    sort_field: str = Query('date', regex='^(date|description|amount|type)$'),
    sort_direction: str = Query('desc', regex='^(asc|desc)$'),
    search: str = Query(None, description="Search term for description/counterparty"),
    category: str = Query(None, description="Category filter (expense or income)"),
    classification_status: str = Query('all', regex='^(all|classified|unclassified)$'),
    start_date: str = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(None, description="End date (YYYY-MM-DD)")
):
    try:
        from sqlalchemy import or_, and_
        from datetime import datetime
        # Map frontend field name to database field name
        db_sort_field = SORT_FIELD_MAPPING.get(sort_field, 'transaction_date')
        
        # Build the base query
        query = db.query(Transaction)

        # Apply search filter
        if search:
            ilike_str = f"%{search.lower()}%"
            query = query.filter(
                or_(
                    func.lower(Transaction.description).ilike(ilike_str),
                    func.lower(Transaction.counterparty_name).ilike(ilike_str)
                )
            )
        # Apply category filter
        if category and category != 'all':
            # Try to match ExpenseCategory or IncomeCategory enums
            expense_enum = None
            income_enum = None
            transfer_enum = None
            try:
                expense_enum = ExpenseCategory(category)
            except Exception:
                pass
            try:
                income_enum = IncomeCategory(category)
            except Exception:
                pass
            try:
                transfer_enum = TransferCategory(category)
            except Exception:
                pass
            if expense_enum and income_enum and transfer_enum:
                query = query.filter(
                    or_(
                        Transaction.expense_category == expense_enum,
                        Transaction.income_category == income_enum,
                        Transaction.transfer_category == transfer_enum,
                    )
                )
            elif expense_enum and income_enum:
                query = query.filter(
                    or_(
                        Transaction.expense_category == expense_enum,
                        Transaction.income_category == income_enum
                    )
                )
            elif expense_enum and transfer_enum:
                query = query.filter(
                    or_(
                        Transaction.expense_category == expense_enum,
                        Transaction.transfer_category == transfer_enum,
                    )
                )
            elif income_enum and transfer_enum:
                query = query.filter(
                    or_(
                        Transaction.income_category == income_enum,
                        Transaction.transfer_category == transfer_enum,
                    )
                )
            elif expense_enum:
                query = query.filter(Transaction.expense_category == expense_enum)
            elif income_enum:
                query = query.filter(Transaction.income_category == income_enum)
            elif transfer_enum:
                query = query.filter(Transaction.transfer_category == transfer_enum)
            else:
                query = query.filter(False)  # No match, return empty
        # Apply date range filter
        if start_date:
            try:
                start = datetime.strptime(start_date, "%Y-%m-%d").date()
                query = query.filter(Transaction.transaction_date >= start)
            except Exception:
                pass
        if end_date:
            try:
                end = datetime.strptime(end_date, "%Y-%m-%d").date()
                query = query.filter(Transaction.transaction_date <= end)
            except Exception:
                pass

        if classification_status == 'classified':
            query = query.filter(
                or_(
                    and_(
                        Transaction.transaction_type == TransactionType.EXPENSE,
                        Transaction.expense_category.isnot(None),
                    ),
                    and_(
                        Transaction.transaction_type == TransactionType.INCOME,
                        Transaction.income_category.isnot(None),
                    ),
                    and_(
                        Transaction.transaction_type == TransactionType.TRANSFER,
                        Transaction.transfer_category.isnot(None),
                    ),
                )
            )
        elif classification_status == 'unclassified':
            query = query.filter(
                or_(
                    and_(
                        Transaction.transaction_type == TransactionType.EXPENSE,
                        Transaction.expense_category.is_(None),
                    ),
                    and_(
                        Transaction.transaction_type == TransactionType.INCOME,
                        Transaction.income_category.is_(None),
                    ),
                    and_(
                        Transaction.transaction_type == TransactionType.TRANSFER,
                        Transaction.transfer_category.is_(None),
                    ),
                )
            )

        # Add sorting
        if sort_direction == 'asc':
            sort_column = getattr(Transaction, db_sort_field).asc()
        else:
            sort_column = getattr(Transaction, db_sort_field).desc()
        
        query = query.order_by(sort_column)
        
        # Get total count before pagination
        total_count = query.count()
        
        # Add pagination
        offset = (page - 1) * page_size
        transactions = query.offset(offset).limit(page_size).all()
        
        conversion_service = CurrencyConversionService(db)
        serialized_transactions = [
            _serialize_transaction_for_response(
                transaction,
                conversion_service=conversion_service,
                reporting_currency=reporting_currency,
            )
            for transaction in transactions
        ]

        return {
            "items": serialized_transactions,
            "total": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": (total_count + page_size - 1) // page_size
        }
    except Exception as e:
        logger.error(f"Error fetching transactions: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{transaction_id}")
async def delete_transaction(transaction_id: int, db: Session = Depends(get_db)):
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    transaction_date = transaction.transaction_date
    seeded_pattern_ids = [pattern.id for pattern in transaction.seeded_recurrence_patterns]

    if seeded_pattern_ids:
        (
            db.query(Transaction)
            .filter(Transaction.recurrence_pattern_id.in_(seeded_pattern_ids))
            .update({Transaction.recurrence_pattern_id: None}, synchronize_session=False)
        )
    
    # Delete associated anomaly records first to avoid foreign key constraint violation
    db.query(TransactionAnomaly).filter(TransactionAnomaly.transaction_id == transaction_id).delete()

    for pattern in list(transaction.seeded_recurrence_patterns):
        db.delete(pattern)

    for session in list(transaction.classification_sessions):
        db.delete(session)
    
    # Delete the transaction
    db.delete(transaction)
    
    # Commit deletion before updating statistics
    db.commit()
    
    # Update statistics for the affected period
    StatisticsService.update_statistics(db, transaction_date)
    
    return {"message": "Transaction deleted successfully"}

@router.patch("/{transaction_id}/category")
def update_transaction_category(
    transaction_id: int,
    category: str = Query(...),
    transaction_type: TransactionType = Query(...),
    db: Session = Depends(get_db),
    reporting_currency: str = Depends(get_reporting_currency),
):
    transaction = db.query(Transaction).filter(
        Transaction.id == transaction_id
    ).first()
    
    if not transaction:
        raise HTTPException(404, detail="Transaction not found")

    try:
        updated_transaction = commit_category_change(
            db=db,
            transaction=transaction,
            transaction_type=transaction_type,
            category=category,
            classification_source="manual",
            recurrence_pattern_id=transaction.recurrence_pattern_id,
        )
        conversion_service = CurrencyConversionService(db)
        return _serialize_transaction_for_response(
            updated_transaction,
            conversion_service=conversion_service,
            reporting_currency=reporting_currency,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/restore", response_model=schemas.Transaction)
def restore_transaction(
    transaction_data: schemas.TransactionRestore = Body(...),
    db: Session = Depends(get_db),
    reporting_currency: str = Depends(get_reporting_currency),
):
    try:
        # Create a new transaction with the provided data
        # The ID will be auto-generated, which is fine for our purpose
        new_transaction = Transaction(**transaction_data.dict(exclude={"id"}))
        db.add(new_transaction)
        db.commit()
        db.refresh(new_transaction)
        
        # Update statistics for the affected period
        StatisticsService.update_statistics(db, new_transaction.transaction_date)
        
        # Run anomaly detection on restored transaction
        try:
            AnomalyDetectionService.detect_anomalies(
                db=db,
                transaction_ids=[new_transaction.id],
                force_redetection=False
            )
        except Exception as e:
            logger.warning(f"Anomaly detection failed for restored transaction: {str(e)}")
        
        conversion_service = CurrencyConversionService(db)
        return _serialize_transaction_for_response(
            new_transaction,
            conversion_service=conversion_service,
            reporting_currency=reporting_currency,
        )
        
    except Exception as e:
        logger.error(f"Error restoring transaction: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
