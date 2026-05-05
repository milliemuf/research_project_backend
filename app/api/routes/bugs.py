"""
Bug Management API Routes.

Endpoints for bug detection, listing, and management.
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum

router = APIRouter()


class BugSeverity(str, Enum):
    """Bug severity levels."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class BugStatus(str, Enum):
    """Bug lifecycle status."""
    DETECTED = "detected"
    ANALYZING = "analyzing"
    FIX_PROPOSED = "fix_proposed"
    CONSENSUS_PENDING = "consensus_pending"
    FIXING = "fixing"
    RESOLVED = "resolved"
    FAILED = "failed"


class BugType(str, Enum):
    """Classification of bug types."""
    NULL_POINTER = "null_pointer"
    TYPE_ERROR = "type_error"
    INDEX_OUT_OF_BOUNDS = "index_out_of_bounds"
    DIVISION_BY_ZERO = "division_by_zero"
    API_ERROR = "api_error"
    TIMEOUT = "timeout"
    MEMORY_ERROR = "memory_error"
    SYNTAX_ERROR = "syntax_error"
    LOGIC_ERROR = "logic_error"
    CONCURRENCY_ERROR = "concurrency_error"
    UNKNOWN = "unknown"


class BugCreate(BaseModel):
    """Schema for creating a new bug report."""
    error_message: str = Field(..., description="The error message from the exception")
    stack_trace: str = Field(..., description="Full stack trace")
    code_context: str = Field(..., description="Code surrounding the error location")
    file_path: str = Field(..., description="Path to the file where error occurred")
    line_number: int = Field(..., description="Line number where error occurred")
    language: str = Field(default="python", description="Programming language")
    metadata: Optional[dict] = Field(default=None, description="Additional context")


class BugResponse(BaseModel):
    """Schema for bug response."""
    id: str
    error_message: str
    stack_trace: str
    code_context: str
    file_path: str
    line_number: int
    language: str
    bug_type: BugType
    severity: BugSeverity
    status: BugStatus
    confidence_score: float
    detected_at: datetime
    resolved_at: Optional[datetime] = None
    fix_id: Optional[str] = None


class BugListResponse(BaseModel):
    """Schema for paginated bug list."""
    total: int
    page: int
    per_page: int
    bugs: List[BugResponse]


# In-memory storage for demo (replace with database in production)
bugs_db: dict = {}

# Seed demo data
import uuid
from datetime import timedelta

_demo_bugs = [
    {"error_message": "TypeError: Cannot read property 'total' of undefined", "stack_trace": "at PaymentService.processOrder (services/payment.py:89)\n  at OrderController.checkout (controllers/order.py:45)\n  at Router.handle (core/router.py:112)", "code_context": "def process_order(self, order):\n    total = order.cart.total  # cart is None\n    discount = self.apply_discount(total)\n    return self.gateway.charge(total - discount)", "file_path": "services/payment.py", "line_number": 89, "bug_type": "null_pointer", "severity": "critical", "status": "resolved", "confidence_score": 0.92},
    {"error_message": "FloatingPointError: Decimal precision loss in currency conversion", "stack_trace": "at CurrencyConverter.convert (utils/currency.py:34)\n  at CartService.calculate_total (services/cart.py:67)", "code_context": "def convert(self, amount, from_curr, to_curr):\n    rate = self.get_rate(from_curr, to_curr)\n    return float(amount) * rate  # precision loss", "file_path": "utils/currency.py", "line_number": 34, "bug_type": "logic_error", "severity": "high", "status": "consensus_pending", "confidence_score": 0.85},
    {"error_message": "IndexError: list index out of range in inventory check", "stack_trace": "at InventoryManager.check_stock (services/inventory.py:156)\n  at ProductController.add_to_cart (controllers/product.py:78)", "code_context": "def check_stock(self, product_id, warehouse_idx):\n    warehouses = self.get_warehouses(product_id)\n    return warehouses[warehouse_idx].stock > 0", "file_path": "services/inventory.py", "line_number": 156, "bug_type": "index_out_of_bounds", "severity": "medium", "status": "fix_proposed", "confidence_score": 0.78},
    {"error_message": "TimeoutError: Payment gateway response exceeded 30s limit", "stack_trace": "at PaymentGateway.charge (gateways/stripe.py:45)\n  at PaymentService.process (services/payment.py:23)", "code_context": "async def charge(self, amount, token):\n    response = await self.client.post('/charges', data={\n        'amount': amount, 'token': token\n    })  # no timeout set", "file_path": "gateways/stripe.py", "line_number": 45, "bug_type": "timeout", "severity": "high", "status": "analyzing", "confidence_score": 0.65},
    {"error_message": "RaceCondition: Concurrent inventory update caused overselling", "stack_trace": "at InventoryManager.decrement (services/inventory.py:201)\n  at OrderService.finalize (services/order.py:134)", "code_context": "def decrement(self, product_id, quantity):\n    current = self.get_stock(product_id)\n    if current >= quantity:\n        self.set_stock(product_id, current - quantity)", "file_path": "services/inventory.py", "line_number": 201, "bug_type": "concurrency_error", "severity": "critical", "status": "detected", "confidence_score": 0.0},
    {"error_message": "ZeroDivisionError: division by zero in discount calculation", "stack_trace": "at DiscountEngine.calculate (services/discount.py:78)\n  at CartService.apply_promotions (services/cart.py:145)", "code_context": "def calculate(self, items, promo_code):\n    total_items = len([i for i in items if i.eligible])\n    per_item_discount = self.budget / total_items", "file_path": "services/discount.py", "line_number": 78, "bug_type": "division_by_zero", "severity": "medium", "status": "resolved", "confidence_score": 0.95},
    {"error_message": "APIError: Third-party shipping API returned 503", "stack_trace": "at ShippingService.get_rates (services/shipping.py:56)\n  at CheckoutController.calculate (controllers/checkout.py:89)", "code_context": "def get_rates(self, address, weight):\n    resp = requests.get(f'{self.api_url}/rates', params={\n        'dest': address, 'weight': weight\n    })\n    return resp.json()['rates']  # no error handling", "file_path": "services/shipping.py", "line_number": 56, "bug_type": "api_error", "severity": "low", "status": "resolved", "confidence_score": 0.88},
    {"error_message": "TypeError: unsupported operand type(s) for +: 'int' and 'str'", "stack_trace": "at ReportGenerator.summarize (reports/sales.py:112)\n  at DashboardController.monthly (controllers/dashboard.py:34)", "code_context": "def summarize(self, transactions):\n    total = 0\n    for t in transactions:\n        total += t['amount']  # amount is string from DB", "file_path": "reports/sales.py", "line_number": 112, "bug_type": "type_error", "severity": "medium", "status": "fix_proposed", "confidence_score": 0.82},
]

_now = datetime.utcnow()
for i, b in enumerate(_demo_bugs):
    _id = str(uuid.uuid4())
    bugs_db[_id] = BugResponse(
        id=_id,
        error_message=b["error_message"],
        stack_trace=b["stack_trace"],
        code_context=b["code_context"],
        file_path=b["file_path"],
        line_number=b["line_number"],
        language="python",
        bug_type=BugType(b["bug_type"]),
        severity=BugSeverity(b["severity"]),
        status=BugStatus(b["status"]),
        confidence_score=b["confidence_score"],
        detected_at=_now - timedelta(hours=len(_demo_bugs) - i, minutes=i * 7),
        resolved_at=(_now - timedelta(hours=len(_demo_bugs) - i - 1)) if b["status"] == "resolved" else None,
    )


@router.post("", response_model=BugResponse, status_code=201)
async def create_bug(bug: BugCreate):
    """
    Report a new bug detected in the system.

    This endpoint is called when the runtime monitor detects an error.
    The bug will be processed by the multi-agent system for repair.
    """
    import uuid

    bug_id = str(uuid.uuid4())
    bug_data = BugResponse(
        id=bug_id,
        error_message=bug.error_message,
        stack_trace=bug.stack_trace,
        code_context=bug.code_context,
        file_path=bug.file_path,
        line_number=bug.line_number,
        language=bug.language,
        bug_type=BugType.UNKNOWN,  # Will be classified by Analyzer Agent
        severity=BugSeverity.MEDIUM,  # Will be assessed by Analyzer Agent
        status=BugStatus.DETECTED,
        confidence_score=0.0,
        detected_at=datetime.utcnow(),
    )

    bugs_db[bug_id] = bug_data

    # TODO: Trigger multi-agent repair pipeline
    # await agent_manager.process_bug(bug_data)

    return bug_data


@router.get("", response_model=BugListResponse)
async def list_bugs(
    status: Optional[BugStatus] = Query(None, description="Filter by status"),
    severity: Optional[BugSeverity] = Query(None, description="Filter by severity"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
):
    """List all bugs with optional filtering and pagination."""
    filtered_bugs = list(bugs_db.values())

    if status:
        filtered_bugs = [b for b in filtered_bugs if b.status == status]
    if severity:
        filtered_bugs = [b for b in filtered_bugs if b.severity == severity]

    # Sort by detected_at descending (newest first)
    filtered_bugs.sort(key=lambda x: x.detected_at, reverse=True)

    # Paginate
    start = (page - 1) * per_page
    end = start + per_page
    paginated = filtered_bugs[start:end]

    return BugListResponse(
        total=len(filtered_bugs),
        page=page,
        per_page=per_page,
        bugs=paginated,
    )


@router.get("/stats/summary")
async def get_bug_stats():
    """Get summary statistics about bugs."""
    bugs = list(bugs_db.values())

    status_counts = {}
    severity_counts = {}
    type_counts = {}

    for bug in bugs:
        status_counts[bug.status.value] = status_counts.get(bug.status.value, 0) + 1
        severity_counts[bug.severity.value] = severity_counts.get(bug.severity.value, 0) + 1
        type_counts[bug.bug_type.value] = type_counts.get(bug.bug_type.value, 0) + 1

    resolved = [b for b in bugs if b.status == BugStatus.RESOLVED]
    avg_resolution_time = None
    if resolved:
        times = [(b.resolved_at - b.detected_at).total_seconds() for b in resolved if b.resolved_at]
        if times:
            avg_resolution_time = sum(times) / len(times)

    return {
        "total_bugs": len(bugs),
        "by_status": status_counts,
        "by_severity": severity_counts,
        "by_type": type_counts,
        "avg_resolution_time_seconds": avg_resolution_time,
    }


@router.get("/{bug_id}", response_model=BugResponse)
async def get_bug(bug_id: str):
    """Get details of a specific bug."""
    if bug_id not in bugs_db:
        raise HTTPException(status_code=404, detail="Bug not found")
    return bugs_db[bug_id]
