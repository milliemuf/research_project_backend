"""
E-commerce micro-benchmark — 10 Python bugs that break commerce-domain
invariants. Each case bundles the buggy function with a self-checking test
that asserts BOTH the functional behaviour AND the relevant e-commerce
invariant (idempotency, non-negative inventory, refund cap, currency
coherence, etc.).

This dataset directly addresses Gap 4 of the review (e-commerce as an
unaddressed domain) and §VIII-C of the H-BFT proposal (application-level
invariants embedded in the agreement loop). The invariants are
implemented as additional assertions in the test script, so the existing
sandbox infrastructure exercises them without modification.

Author: Millicent Mufambi (H240624A)
"""
from __future__ import annotations

from typing import List, Optional

from benchmarks.bug_case import BugCase


def _case(
    bug_id: str,
    buggy: str,
    fixed: str,
    error_message: str,
    stack_trace: str,
    line_number: int,
    bug_category: str,
    invariant: str,
) -> BugCase:
    return BugCase(
        bug_id=bug_id,
        project="ecommerce",
        error_message=error_message,
        stack_trace=stack_trace,
        code_context=buggy,
        file_path="main.py",
        line_number=line_number,
        language="python",
        test_command=["python", "main.py"],
        canonical_fixed_code=fixed,
        metadata={
            "bug_category": bug_category,
            "invariant_violated": invariant,
            "domain": "e-commerce",
        },
    )


_CASES: List[BugCase] = [
    # --- 1. Payment idempotency ----------------------------------------------
    _case(
        bug_id="ec-001-payment-idempotency",
        bug_category="payment-idempotency",
        invariant="idempotent_payment",
        line_number=2,
        error_message="AssertionError: idempotency violated: same payment processed twice",
        stack_trace=(
            'Traceback (most recent call last):\n'
            '  File "main.py", line 16, in <module>\n'
            "    assert account['balance'] == 900, 'idempotency violated'\n"
            "AssertionError: idempotency violated: same payment processed twice"
        ),
        buggy=(
            "def process_payment(account, amount, idem_key, ledger):\n"
            "    account['balance'] -= amount\n"
            "    ledger.append({'idem_key': idem_key, 'amount': amount})\n"
            "    return {'status': 'charged', 'amount': amount}\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    account = {'balance': 1000}\n"
            "    ledger = []\n"
            "    process_payment(account, 100, 'tx-1', ledger)\n"
            "    process_payment(account, 100, 'tx-1', ledger)  # retry with same key\n"
            "    assert account['balance'] == 900, 'idempotency violated: same payment processed twice'\n"
            "    print('ok')\n"
        ),
        fixed=(
            "def process_payment(account, amount, idem_key, ledger):\n"
            "    if any(e['idem_key'] == idem_key for e in ledger):\n"
            "        return {'status': 'duplicate', 'amount': 0}\n"
            "    account['balance'] -= amount\n"
            "    ledger.append({'idem_key': idem_key, 'amount': amount})\n"
            "    return {'status': 'charged', 'amount': amount}\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    account = {'balance': 1000}\n"
            "    ledger = []\n"
            "    process_payment(account, 100, 'tx-1', ledger)\n"
            "    process_payment(account, 100, 'tx-1', ledger)  # retry with same key\n"
            "    assert account['balance'] == 900, 'idempotency violated: same payment processed twice'\n"
            "    print('ok')\n"
        ),
    ),
    # --- 2. Negative inventory -----------------------------------------------
    _case(
        bug_id="ec-002-negative-inventory",
        bug_category="inventory",
        invariant="non_negative_inventory",
        line_number=2,
        error_message="AssertionError: inventory went negative (oversold)",
        stack_trace=(
            'Traceback (most recent call last):\n'
            '  File "main.py", line 11, in <module>\n'
            "    assert item['stock'] >= 0, 'inventory went negative'\n"
            "AssertionError: inventory went negative (oversold)"
        ),
        buggy=(
            "def reserve_stock(item, quantity):\n"
            "    item['stock'] -= quantity\n"
            "    return {'reserved': quantity}\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    item = {'sku': 'A1', 'stock': 5}\n"
            "    reserve_stock(item, 3)\n"
            "    reserve_stock(item, 4)  # only 2 left, but asks for 4\n"
            "    assert item['stock'] >= 0, 'inventory went negative (oversold)'\n"
            "    print('ok')\n"
        ),
        fixed=(
            "def reserve_stock(item, quantity):\n"
            "    if quantity > item['stock']:\n"
            "        return {'reserved': 0, 'error': 'insufficient_stock'}\n"
            "    item['stock'] -= quantity\n"
            "    return {'reserved': quantity}\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    item = {'sku': 'A1', 'stock': 5}\n"
            "    reserve_stock(item, 3)\n"
            "    reserve_stock(item, 4)\n"
            "    assert item['stock'] >= 0, 'inventory went negative (oversold)'\n"
            "    print('ok')\n"
        ),
    ),
    # --- 3. Tax double-application -------------------------------------------
    _case(
        bug_id="ec-003-tax-double-application",
        bug_category="tax-calculation",
        invariant="single_tax_application",
        line_number=3,
        error_message="AssertionError: tax was applied twice",
        stack_trace=(
            'Traceback (most recent call last):\n'
            '  File "main.py", line 8, in <module>\n'
            "    assert abs(total - 115.0) < 0.01, 'tax applied twice'\n"
            "AssertionError: tax was applied twice"
        ),
        buggy=(
            "def total_with_tax(subtotal, tax_rate=0.15):\n"
            "    tax = subtotal * tax_rate\n"
            "    return subtotal + tax + tax\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    total = total_with_tax(100.0, 0.15)\n"
            "    assert abs(total - 115.0) < 0.01, 'tax was applied twice'\n"
            "    print('ok')\n"
        ),
        fixed=(
            "def total_with_tax(subtotal, tax_rate=0.15):\n"
            "    tax = subtotal * tax_rate\n"
            "    return subtotal + tax\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    total = total_with_tax(100.0, 0.15)\n"
            "    assert abs(total - 115.0) < 0.01, 'tax was applied twice'\n"
            "    print('ok')\n"
        ),
    ),
    # --- 4. Currency rounding (split payment) --------------------------------
    _case(
        bug_id="ec-004-currency-rounding",
        bug_category="currency-rounding",
        invariant="split_sums_to_total",
        line_number=2,
        error_message="AssertionError: split payments do not sum to original",
        stack_trace=(
            'Traceback (most recent call last):\n'
            '  File "main.py", line 9, in <module>\n'
            "    assert abs(sum(splits) - amount) < 0.01\n"
            "AssertionError: split payments do not sum to original"
        ),
        buggy=(
            "def split_payment(amount_cents, n):\n"
            "    return [amount_cents // n] * n\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    amount = 1000  # 10.00 in cents\n"
            "    splits = split_payment(amount, 3)\n"
            "    assert sum(splits) == amount, 'split payments do not sum to original'\n"
            "    print('ok')\n"
        ),
        fixed=(
            "def split_payment(amount_cents, n):\n"
            "    base = amount_cents // n\n"
            "    remainder = amount_cents - base * n\n"
            "    return [base + (1 if i < remainder else 0) for i in range(n)]\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    amount = 1000\n"
            "    splits = split_payment(amount, 3)\n"
            "    assert sum(splits) == amount, 'split payments do not sum to original'\n"
            "    print('ok')\n"
        ),
    ),
    # --- 5. Discount stacking compounds --------------------------------------
    _case(
        bug_id="ec-005-discount-overstack",
        bug_category="discount-stacking",
        invariant="discount_capped",
        line_number=3,
        error_message="AssertionError: stacked discounts exceeded cap",
        stack_trace=(
            'Traceback (most recent call last):\n'
            '  File "main.py", line 10, in <module>\n'
            "    assert final >= price * 0.5, 'stacked discounts exceeded cap'\n"
            "AssertionError: stacked discounts exceeded cap"
        ),
        buggy=(
            "def apply_discounts(price, discounts, max_total_discount=0.5):\n"
            "    for d in discounts:\n"
            "        price *= (1 - d)\n"
            "    return price\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    price = 100.0\n"
            "    discounts = [0.3, 0.3, 0.3]  # 90% combined far exceeds 50% cap\n"
            "    final = apply_discounts(price, discounts)\n"
            "    assert final >= price * 0.5, 'stacked discounts exceeded cap'\n"
            "    print('ok')\n"
        ),
        fixed=(
            "def apply_discounts(price, discounts, max_total_discount=0.5):\n"
            "    total_discount = min(sum(discounts), max_total_discount)\n"
            "    return price * (1 - total_discount)\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    price = 100.0\n"
            "    discounts = [0.3, 0.3, 0.3]\n"
            "    final = apply_discounts(price, discounts)\n"
            "    assert final >= price * 0.5, 'stacked discounts exceeded cap'\n"
            "    print('ok')\n"
        ),
    ),
    # --- 6. Cart total ignores quantity --------------------------------------
    _case(
        bug_id="ec-006-cart-total-ignores-qty",
        bug_category="cart-total",
        invariant="total_equals_sum_qty_price",
        line_number=2,
        error_message="AssertionError: cart total does not equal sum(price * qty)",
        stack_trace=(
            'Traceback (most recent call last):\n'
            '  File "main.py", line 9, in <module>\n'
            "    assert total == 70.0\n"
            "AssertionError: cart total does not equal sum(price * qty)"
        ),
        buggy=(
            "def cart_total(items):\n"
            "    return sum(i['price'] for i in items)\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    items = [\n"
            "        {'sku': 'A', 'price': 10.0, 'qty': 3},\n"
            "        {'sku': 'B', 'price': 20.0, 'qty': 2},\n"
            "    ]\n"
            "    total = cart_total(items)\n"
            "    assert total == 70.0, 'cart total does not equal sum(price * qty)'\n"
            "    print('ok')\n"
        ),
        fixed=(
            "def cart_total(items):\n"
            "    return sum(i['price'] * i['qty'] for i in items)\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    items = [\n"
            "        {'sku': 'A', 'price': 10.0, 'qty': 3},\n"
            "        {'sku': 'B', 'price': 20.0, 'qty': 2},\n"
            "    ]\n"
            "    total = cart_total(items)\n"
            "    assert total == 70.0, 'cart total does not equal sum(price * qty)'\n"
            "    print('ok')\n"
        ),
    ),
    # --- 7. Refund exceeds original ------------------------------------------
    _case(
        bug_id="ec-007-refund-exceeds-original",
        bug_category="refund-cap",
        invariant="refund_le_payment",
        line_number=2,
        error_message="AssertionError: refund exceeded original payment",
        stack_trace=(
            'Traceback (most recent call last):\n'
            '  File "main.py", line 10, in <module>\n'
            "    assert payment['refunded'] <= payment['amount']\n"
            "AssertionError: refund exceeded original payment"
        ),
        buggy=(
            "def refund(payment, refund_amount):\n"
            "    payment['refunded'] += refund_amount\n"
            "    return {'refunded': refund_amount}\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    payment = {'amount': 100, 'refunded': 0}\n"
            "    refund(payment, 60)\n"
            "    refund(payment, 50)  # cumulative 110 > 100\n"
            "    assert payment['refunded'] <= payment['amount'], 'refund exceeded original payment'\n"
            "    print('ok')\n"
        ),
        fixed=(
            "def refund(payment, refund_amount):\n"
            "    available = payment['amount'] - payment['refunded']\n"
            "    actual = min(refund_amount, available)\n"
            "    payment['refunded'] += actual\n"
            "    return {'refunded': actual}\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    payment = {'amount': 100, 'refunded': 0}\n"
            "    refund(payment, 60)\n"
            "    refund(payment, 50)\n"
            "    assert payment['refunded'] <= payment['amount'], 'refund exceeded original payment'\n"
            "    print('ok')\n"
        ),
    ),
    # --- 8. Coupon expiry not checked ----------------------------------------
    _case(
        bug_id="ec-008-expired-coupon-applied",
        bug_category="coupon-expiry",
        invariant="expired_coupon_rejected",
        line_number=2,
        error_message="AssertionError: expired coupon was still applied",
        stack_trace=(
            'Traceback (most recent call last):\n'
            '  File "main.py", line 11, in <module>\n'
            "    assert price == 100.0, 'expired coupon was still applied'\n"
            "AssertionError: expired coupon was still applied"
        ),
        buggy=(
            "def apply_coupon(price, coupon, today):\n"
            "    return price * (1 - coupon['discount'])\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    coupon = {'code': 'SAVE10', 'discount': 0.1, 'expires': '2024-01-01'}\n"
            "    today = '2025-06-01'\n"
            "    price = apply_coupon(100.0, coupon, today)\n"
            "    assert price == 100.0, 'expired coupon was still applied'\n"
            "    print('ok')\n"
        ),
        fixed=(
            "def apply_coupon(price, coupon, today):\n"
            "    if today > coupon['expires']:\n"
            "        return price\n"
            "    return price * (1 - coupon['discount'])\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    coupon = {'code': 'SAVE10', 'discount': 0.1, 'expires': '2024-01-01'}\n"
            "    today = '2025-06-01'\n"
            "    price = apply_coupon(100.0, coupon, today)\n"
            "    assert price == 100.0, 'expired coupon was still applied'\n"
            "    print('ok')\n"
        ),
    ),
    # --- 9. Order state machine bypass ---------------------------------------
    _case(
        bug_id="ec-009-order-state-bypass",
        bug_category="state-machine",
        invariant="cancel_only_when_pending",
        line_number=2,
        error_message="AssertionError: shipped order should not have been cancellable",
        stack_trace=(
            'Traceback (most recent call last):\n'
            '  File "main.py", line 9, in <module>\n'
            "    assert order['status'] == 'shipped', 'shipped order was cancelled'\n"
            "AssertionError: shipped order should not have been cancellable"
        ),
        buggy=(
            "def cancel_order(order):\n"
            "    order['status'] = 'cancelled'\n"
            "    return order\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    order = {'id': 'O1', 'status': 'shipped'}\n"
            "    cancel_order(order)\n"
            "    assert order['status'] == 'shipped', 'shipped order should not have been cancellable'\n"
            "    pending = {'id': 'O2', 'status': 'pending'}\n"
            "    cancel_order(pending)\n"
            "    assert pending['status'] == 'cancelled'\n"
            "    print('ok')\n"
        ),
        fixed=(
            "def cancel_order(order):\n"
            "    if order['status'] == 'pending':\n"
            "        order['status'] = 'cancelled'\n"
            "    return order\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    order = {'id': 'O1', 'status': 'shipped'}\n"
            "    cancel_order(order)\n"
            "    assert order['status'] == 'shipped', 'shipped order should not have been cancellable'\n"
            "    pending = {'id': 'O2', 'status': 'pending'}\n"
            "    cancel_order(pending)\n"
            "    assert pending['status'] == 'cancelled'\n"
            "    print('ok')\n"
        ),
    ),
    # --- 10. Inventory not decremented after sale ----------------------------
    _case(
        bug_id="ec-010-stock-not-decremented",
        bug_category="inventory",
        invariant="stock_decreases_on_sale",
        line_number=3,
        error_message="AssertionError: stock did not decrease after sale",
        stack_trace=(
            'Traceback (most recent call last):\n'
            '  File "main.py", line 10, in <module>\n'
            "    assert item['stock'] == 7, 'stock did not decrease after sale'\n"
            "AssertionError: stock did not decrease after sale"
        ),
        buggy=(
            "def complete_sale(item, qty):\n"
            "    revenue = item['price'] * qty\n"
            "    return {'revenue': revenue}\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    item = {'sku': 'X1', 'price': 5.0, 'stock': 10}\n"
            "    complete_sale(item, 3)\n"
            "    assert item['stock'] == 7, 'stock did not decrease after sale'\n"
            "    print('ok')\n"
        ),
        fixed=(
            "def complete_sale(item, qty):\n"
            "    revenue = item['price'] * qty\n"
            "    item['stock'] -= qty\n"
            "    return {'revenue': revenue}\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    item = {'sku': 'X1', 'price': 5.0, 'stock': 10}\n"
            "    complete_sale(item, 3)\n"
            "    assert item['stock'] == 7, 'stock did not decrease after sale'\n"
            "    print('ok')\n"
        ),
    ),
]


def load(limit: Optional[int] = None) -> List[BugCase]:
    if limit is None:
        return list(_CASES)
    return list(_CASES[:limit])


def case_ids() -> List[str]:
    return [c.bug_id for c in _CASES]
