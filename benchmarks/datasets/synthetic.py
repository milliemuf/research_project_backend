"""
Synthetic micro-benchmark — 10 small Python bugs that can be exercised
end-to-end without any external dataset infrastructure.

Each case packages:
  * a complete .py file containing a buggy function AND a self-checking
    `if __name__ == '__main__':` block that asserts the correct behaviour
  * a synthetic but realistic-looking error message and stack trace
  * the canonical fixed version of the same file

The test command is simply `python main.py`. If the fix is correct the
script exits 0. If not, the assertion fails and the script exits non-zero.

This is intentionally simple. Its purpose is to validate the entire
repair pipeline end-to-end on a problem set that runs in seconds, not
minutes.
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
    bug_type: str,
) -> BugCase:
    return BugCase(
        bug_id=bug_id,
        project="synthetic",
        error_message=error_message,
        stack_trace=stack_trace,
        code_context=buggy,
        file_path="main.py",
        line_number=line_number,
        language="python",
        test_command=["python", "main.py"],
        canonical_fixed_code=fixed,
        metadata={"bug_type": bug_type, "category": "single-function"},
    )


_CASES: List[BugCase] = [
    # ------------------------------------------------------------------
    _case(
        bug_id="syn-001-off-by-one",
        bug_type="off-by-one",
        line_number=3,
        error_message="IndexError: list index out of range",
        stack_trace=(
            'Traceback (most recent call last):\n'
            '  File "main.py", line 11, in <module>\n'
            '    assert sum_first_n([1, 2, 3, 4, 5], 5) == 15\n'
            '  File "main.py", line 4, in sum_first_n\n'
            '    total += xs[i]\n'
            'IndexError: list index out of range'
        ),
        buggy=(
            "def sum_first_n(xs, n):\n"
            "    total = 0\n"
            "    for i in range(n + 1):\n"
            "        total += xs[i]\n"
            "    return total\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert sum_first_n([1, 2, 3, 4, 5], 5) == 15\n"
            "    assert sum_first_n([10, 20, 30], 2) == 30\n"
            "    print('ok')\n"
        ),
        fixed=(
            "def sum_first_n(xs, n):\n"
            "    total = 0\n"
            "    for i in range(n):\n"
            "        total += xs[i]\n"
            "    return total\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert sum_first_n([1, 2, 3, 4, 5], 5) == 15\n"
            "    assert sum_first_n([10, 20, 30], 2) == 30\n"
            "    print('ok')\n"
        ),
    ),
    # ------------------------------------------------------------------
    _case(
        bug_id="syn-002-mutable-default",
        bug_type="mutable-default-argument",
        line_number=1,
        error_message="AssertionError: append leaks across calls",
        stack_trace=(
            'Traceback (most recent call last):\n'
            '  File "main.py", line 9, in <module>\n'
            '    assert append(2) == [2]\n'
            'AssertionError: append leaks across calls'
        ),
        buggy=(
            "def append(item, bucket=[]):\n"
            "    bucket.append(item)\n"
            "    return bucket\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert append(1) == [1]\n"
            "    assert append(2) == [2], 'append leaks across calls'\n"
            "    print('ok')\n"
        ),
        fixed=(
            "def append(item, bucket=None):\n"
            "    if bucket is None:\n"
            "        bucket = []\n"
            "    bucket.append(item)\n"
            "    return bucket\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert append(1) == [1]\n"
            "    assert append(2) == [2], 'append leaks across calls'\n"
            "    print('ok')\n"
        ),
    ),
    # ------------------------------------------------------------------
    _case(
        bug_id="syn-003-int-vs-float-div",
        bug_type="incorrect-arithmetic",
        line_number=4,
        error_message="AssertionError: average rounded down",
        stack_trace=(
            'Traceback (most recent call last):\n'
            '  File "main.py", line 9, in <module>\n'
            '    assert abs(average([1, 2, 4]) - 2.333) < 0.01\n'
            'AssertionError: average rounded down'
        ),
        buggy=(
            "def average(xs):\n"
            "    if not xs:\n"
            "        return 0\n"
            "    return sum(xs) // len(xs)\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert abs(average([1, 2, 4]) - 2.333) < 0.01, 'average rounded down'\n"
            "    print('ok')\n"
        ),
        fixed=(
            "def average(xs):\n"
            "    if not xs:\n"
            "        return 0\n"
            "    return sum(xs) / len(xs)\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert abs(average([1, 2, 4]) - 2.333) < 0.01, 'average rounded down'\n"
            "    print('ok')\n"
        ),
    ),
    # ------------------------------------------------------------------
    _case(
        bug_id="syn-004-none-attribute",
        bug_type="missing-none-check",
        line_number=4,
        error_message="AttributeError: 'NoneType' object has no attribute 'upper'",
        stack_trace=(
            'Traceback (most recent call last):\n'
            '  File "main.py", line 10, in <module>\n'
            '    assert greet(None) == \'\'\n'
            '  File "main.py", line 4, in greet\n'
            '    return name.upper()\n'
            "AttributeError: 'NoneType' object has no attribute 'upper'"
        ),
        buggy=(
            "def greet(name):\n"
            "    return name.upper()\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert greet('alice') == 'ALICE'\n"
            "    assert greet(None) == ''\n"
            "    print('ok')\n"
        ),
        fixed=(
            "def greet(name):\n"
            "    if name is None:\n"
            "        return ''\n"
            "    return name.upper()\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert greet('alice') == 'ALICE'\n"
            "    assert greet(None) == ''\n"
            "    print('ok')\n"
        ),
    ),
    # ------------------------------------------------------------------
    _case(
        bug_id="syn-005-str-int-concat",
        bug_type="type-error",
        line_number=2,
        error_message="TypeError: can only concatenate str (not \"int\") to str",
        stack_trace=(
            'Traceback (most recent call last):\n'
            '  File "main.py", line 7, in <module>\n'
            '    assert label(5) == \'count: 5\'\n'
            '  File "main.py", line 2, in label\n'
            '    return \'count: \' + n\n'
            "TypeError: can only concatenate str (not \"int\") to str"
        ),
        buggy=(
            "def label(n):\n"
            "    return 'count: ' + n\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert label(5) == 'count: 5'\n"
            "    assert label(0) == 'count: 0'\n"
            "    print('ok')\n"
        ),
        fixed=(
            "def label(n):\n"
            "    return 'count: ' + str(n)\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert label(5) == 'count: 5'\n"
            "    assert label(0) == 'count: 0'\n"
            "    print('ok')\n"
        ),
    ),
    # ------------------------------------------------------------------
    _case(
        bug_id="syn-006-slice-off-by-one",
        bug_type="off-by-one",
        line_number=2,
        error_message="AssertionError: tail slice wrong",
        stack_trace=(
            'Traceback (most recent call last):\n'
            '  File "main.py", line 7, in <module>\n'
            '    assert all_but_last(\'hello\') == \'hell\'\n'
            "AssertionError: tail slice wrong"
        ),
        buggy=(
            "def all_but_last(s):\n"
            "    return s[1:-1]\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert all_but_last('hello') == 'hell', 'tail slice wrong'\n"
            "    assert all_but_last('a') == ''\n"
            "    print('ok')\n"
        ),
        fixed=(
            "def all_but_last(s):\n"
            "    return s[:-1]\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert all_but_last('hello') == 'hell', 'tail slice wrong'\n"
            "    assert all_but_last('a') == ''\n"
            "    print('ok')\n"
        ),
    ),
    # ------------------------------------------------------------------
    _case(
        bug_id="syn-007-missing-return",
        bug_type="missing-return",
        line_number=3,
        error_message="AssertionError: function returned None",
        stack_trace=(
            'Traceback (most recent call last):\n'
            '  File "main.py", line 7, in <module>\n'
            '    assert square(4) == 16\n'
            "AssertionError: function returned None"
        ),
        buggy=(
            "def square(x):\n"
            "    result = x * x\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert square(4) == 16, 'function returned None'\n"
            "    assert square(0) == 0\n"
            "    print('ok')\n"
        ),
        fixed=(
            "def square(x):\n"
            "    result = x * x\n"
            "    return result\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert square(4) == 16, 'function returned None'\n"
            "    assert square(0) == 0\n"
            "    print('ok')\n"
        ),
    ),
    # ------------------------------------------------------------------
    _case(
        bug_id="syn-008-wrong-comparison",
        bug_type="wrong-operator",
        line_number=2,
        error_message="AssertionError: identity vs equality",
        stack_trace=(
            'Traceback (most recent call last):\n'
            '  File "main.py", line 7, in <module>\n'
            '    assert is_one(int(\"1\"))\n'
            "AssertionError: identity vs equality"
        ),
        buggy=(
            "def is_one(x):\n"
            "    return x is 1\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert is_one(1)\n"
            "    assert is_one(int('1')), 'identity vs equality'\n"
            "    print('ok')\n"
        ),
        fixed=(
            "def is_one(x):\n"
            "    return x == 1\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert is_one(1)\n"
            "    assert is_one(int('1')), 'identity vs equality'\n"
            "    print('ok')\n"
        ),
    ),
    # ------------------------------------------------------------------
    _case(
        bug_id="syn-009-key-typo",
        bug_type="dict-key-typo",
        line_number=2,
        error_message="KeyError: 'price'",
        stack_trace=(
            'Traceback (most recent call last):\n'
            '  File "main.py", line 7, in <module>\n'
            '    assert total({\'price\': 10, \'qty\': 3}) == 30\n'
            '  File "main.py", line 2, in total\n'
            '    return order[\'pric\'] * order[\'qty\']\n'
            "KeyError: 'pric'"
        ),
        buggy=(
            "def total(order):\n"
            "    return order['pric'] * order['qty']\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert total({'price': 10, 'qty': 3}) == 30\n"
            "    assert total({'price': 5, 'qty': 4}) == 20\n"
            "    print('ok')\n"
        ),
        fixed=(
            "def total(order):\n"
            "    return order['price'] * order['qty']\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert total({'price': 10, 'qty': 3}) == 30\n"
            "    assert total({'price': 5, 'qty': 4}) == 20\n"
            "    print('ok')\n"
        ),
    ),
    # ------------------------------------------------------------------
    _case(
        bug_id="syn-010-zero-division",
        bug_type="missing-zero-check",
        line_number=2,
        error_message="ZeroDivisionError: division by zero",
        stack_trace=(
            'Traceback (most recent call last):\n'
            '  File "main.py", line 7, in <module>\n'
            '    assert safe_div(10, 0) == 0\n'
            '  File "main.py", line 2, in safe_div\n'
            '    return a / b\n'
            "ZeroDivisionError: division by zero"
        ),
        buggy=(
            "def safe_div(a, b):\n"
            "    return a / b\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert safe_div(10, 2) == 5\n"
            "    assert safe_div(10, 0) == 0\n"
            "    print('ok')\n"
        ),
        fixed=(
            "def safe_div(a, b):\n"
            "    if b == 0:\n"
            "        return 0\n"
            "    return a / b\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert safe_div(10, 2) == 5\n"
            "    assert safe_div(10, 0) == 0\n"
            "    print('ok')\n"
        ),
    ),
    # ------------------------------------------------------------------
    _case(
        bug_id="syn-011-list-mutation-during-iter",
        bug_type="iteration-mutation",
        line_number=3,
        error_message="AssertionError: removed wrong elements",
        stack_trace=(
            'Traceback (most recent call last):\n'
            '  File "main.py", line 9, in <module>\n'
            '    assert remove_evens([1,2,3,4,5,6]) == [1,3,5]\n'
            "AssertionError: removed wrong elements"
        ),
        buggy=(
            "def remove_evens(xs):\n"
            "    for x in xs[:]:\n"
            "        pass\n"
            "    return [x for x in xs if x % 2 != 0]\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    a = [1, 2, 3, 4, 5, 6]\n"
            "    res = remove_evens(a)\n"
            "    assert res == [1, 3, 5], 'removed wrong elements'\n"
            "    print('ok')\n"
        ),
        fixed=(
            "def remove_evens(xs):\n"
            "    return [x for x in xs if x % 2 != 0]\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    a = [1, 2, 3, 4, 5, 6]\n"
            "    res = remove_evens(a)\n"
            "    assert res == [1, 3, 5], 'removed wrong elements'\n"
            "    print('ok')\n"
        ),
    ),
    # ------------------------------------------------------------------
    _case(
        bug_id="syn-012-shadow-builtin",
        bug_type="builtin-shadow",
        line_number=2,
        error_message="TypeError: 'list' object is not callable",
        stack_trace=(
            'Traceback (most recent call last):\n'
            '  File "main.py", line 9, in <module>\n'
            '    assert collect([1, 2, 3]) == [1, 2, 3]\n'
            '  File "main.py", line 3, in collect\n'
            '    return list(items)\n'
            "TypeError: 'list' object is not callable"
        ),
        buggy=(
            "def collect(items):\n"
            "    list = []   # bug: shadows the built-in\n"
            "    return list(items)\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert collect([1, 2, 3]) == [1, 2, 3]\n"
            "    print('ok')\n"
        ),
        fixed=(
            "def collect(items):\n"
            "    result = []\n"
            "    return list(items)\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert collect([1, 2, 3]) == [1, 2, 3]\n"
            "    print('ok')\n"
        ),
    ),
    # ------------------------------------------------------------------
    _case(
        bug_id="syn-013-wrong-loop-var",
        bug_type="wrong-variable",
        line_number=3,
        error_message="AssertionError: only saw last item",
        stack_trace=(
            'Traceback (most recent call last):\n'
            '  File "main.py", line 9, in <module>\n'
            '    assert sum_all([1,2,3,4]) == 10\n'
            "AssertionError: only saw last item"
        ),
        buggy=(
            "def sum_all(xs):\n"
            "    total = 0\n"
            "    for x in xs:\n"
            "        total = x   # bug: assigns instead of adding\n"
            "    return total\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert sum_all([1, 2, 3, 4]) == 10, 'only saw last item'\n"
            "    print('ok')\n"
        ),
        fixed=(
            "def sum_all(xs):\n"
            "    total = 0\n"
            "    for x in xs:\n"
            "        total += x\n"
            "    return total\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert sum_all([1, 2, 3, 4]) == 10, 'only saw last item'\n"
            "    print('ok')\n"
        ),
    ),
    # ------------------------------------------------------------------
    _case(
        bug_id="syn-014-empty-list-default",
        bug_type="missing-empty-check",
        line_number=2,
        error_message="ValueError: max() arg is an empty sequence",
        stack_trace=(
            'Traceback (most recent call last):\n'
            '  File "main.py", line 8, in <module>\n'
            '    assert highest([]) is None\n'
            '  File "main.py", line 2, in highest\n'
            '    return max(xs)\n'
            "ValueError: max() arg is an empty sequence"
        ),
        buggy=(
            "def highest(xs):\n"
            "    return max(xs)\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert highest([3, 1, 4, 1, 5]) == 5\n"
            "    assert highest([]) is None\n"
            "    print('ok')\n"
        ),
        fixed=(
            "def highest(xs):\n"
            "    if not xs:\n"
            "        return None\n"
            "    return max(xs)\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert highest([3, 1, 4, 1, 5]) == 5\n"
            "    assert highest([]) is None\n"
            "    print('ok')\n"
        ),
    ),
    # ------------------------------------------------------------------
    _case(
        bug_id="syn-015-string-format-types",
        bug_type="format-mismatch",
        line_number=2,
        error_message="ValueError: Unknown format code 'd' for object of type 'float'",
        stack_trace=(
            'Traceback (most recent call last):\n'
            '  File "main.py", line 7, in <module>\n'
            '    assert price_label(9.99) == \'price: 9\'\n'
            '  File "main.py", line 2, in price_label\n'
            "    return f'price: {p:d}'\n"
            "ValueError: Unknown format code 'd' for object of type 'float'"
        ),
        buggy=(
            "def price_label(p):\n"
            "    return f'price: {p:d}'\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert price_label(9.99) == 'price: 9'\n"
            "    assert price_label(10) == 'price: 10'\n"
            "    print('ok')\n"
        ),
        fixed=(
            "def price_label(p):\n"
            "    return f'price: {int(p)}'\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert price_label(9.99) == 'price: 9'\n"
            "    assert price_label(10) == 'price: 10'\n"
            "    print('ok')\n"
        ),
    ),
    # ------------------------------------------------------------------
    _case(
        bug_id="syn-016-late-binding-closure",
        bug_type="late-binding",
        line_number=3,
        error_message="AssertionError: all closures returned the same value",
        stack_trace=(
            'Traceback (most recent call last):\n'
            '  File "main.py", line 11, in <module>\n'
            '    assert [f() for f in fns] == [0, 1, 2]\n'
            "AssertionError: all closures returned the same value"
        ),
        buggy=(
            "def make_fns():\n"
            "    fns = []\n"
            "    for i in range(3):\n"
            "        fns.append(lambda: i)\n"
            "    return fns\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    fns = make_fns()\n"
            "    assert [f() for f in fns] == [0, 1, 2], 'all closures returned the same value'\n"
            "    print('ok')\n"
        ),
        fixed=(
            "def make_fns():\n"
            "    fns = []\n"
            "    for i in range(3):\n"
            "        fns.append(lambda i=i: i)\n"
            "    return fns\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    fns = make_fns()\n"
            "    assert [f() for f in fns] == [0, 1, 2], 'all closures returned the same value'\n"
            "    print('ok')\n"
        ),
    ),
    # ------------------------------------------------------------------
    _case(
        bug_id="syn-017-int-overflow-confusion",
        bug_type="boolean-logic",
        line_number=2,
        error_message="AssertionError: range check inverted",
        stack_trace=(
            'Traceback (most recent call last):\n'
            '  File "main.py", line 8, in <module>\n'
            '    assert in_range(5)\n'
            "AssertionError: range check inverted"
        ),
        buggy=(
            "def in_range(x, low=0, high=10):\n"
            "    return x < low or x > high\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert in_range(5), 'range check inverted'\n"
            "    assert not in_range(-1)\n"
            "    print('ok')\n"
        ),
        fixed=(
            "def in_range(x, low=0, high=10):\n"
            "    return low <= x <= high\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert in_range(5), 'range check inverted'\n"
            "    assert not in_range(-1)\n"
            "    print('ok')\n"
        ),
    ),
    # ------------------------------------------------------------------
    _case(
        bug_id="syn-018-recursion-no-base",
        bug_type="missing-base-case",
        line_number=2,
        error_message="RecursionError: maximum recursion depth exceeded",
        stack_trace=(
            'Traceback (most recent call last):\n'
            '  File "main.py", line 7, in <module>\n'
            '    assert factorial(5) == 120\n'
            '  File "main.py", line 2, in factorial\n'
            '    return n * factorial(n - 1)\n'
            "RecursionError: maximum recursion depth exceeded"
        ),
        buggy=(
            "def factorial(n):\n"
            "    return n * factorial(n - 1)\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert factorial(0) == 1\n"
            "    assert factorial(5) == 120\n"
            "    print('ok')\n"
        ),
        fixed=(
            "def factorial(n):\n"
            "    if n <= 1:\n"
            "        return 1\n"
            "    return n * factorial(n - 1)\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert factorial(0) == 1\n"
            "    assert factorial(5) == 120\n"
            "    print('ok')\n"
        ),
    ),
    # ------------------------------------------------------------------
    _case(
        bug_id="syn-019-misuse-walrus",
        bug_type="logic-error",
        line_number=3,
        error_message="AssertionError: counted past end",
        stack_trace=(
            'Traceback (most recent call last):\n'
            '  File "main.py", line 11, in <module>\n'
            '    assert count_until([1,2,3,0,4,5], 0) == 3\n'
            "AssertionError: counted past end"
        ),
        buggy=(
            "def count_until(xs, sentinel):\n"
            "    n = 0\n"
            "    for x in xs:\n"
            "        n += 1   # bug: increments before sentinel check\n"
            "        if x == sentinel:\n"
            "            break\n"
            "    return n\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert count_until([1, 2, 3, 0, 4, 5], 0) == 3, 'counted past end'\n"
            "    print('ok')\n"
        ),
        fixed=(
            "def count_until(xs, sentinel):\n"
            "    n = 0\n"
            "    for x in xs:\n"
            "        if x == sentinel:\n"
            "            break\n"
            "        n += 1\n"
            "    return n\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    assert count_until([1, 2, 3, 0, 4, 5], 0) == 3, 'counted past end'\n"
            "    print('ok')\n"
        ),
    ),
    # ------------------------------------------------------------------
    _case(
        bug_id="syn-020-dict-shallow-copy",
        bug_type="reference-aliasing",
        line_number=4,
        error_message="AssertionError: original was mutated",
        stack_trace=(
            'Traceback (most recent call last):\n'
            '  File "main.py", line 11, in <module>\n'
            '    assert original == {\'a\': 1}\n'
            "AssertionError: original was mutated"
        ),
        buggy=(
            "def with_extra(d, k, v):\n"
            "    out = d   # bug: alias, not copy\n"
            "    out[k] = v\n"
            "    return out\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    original = {'a': 1}\n"
            "    new = with_extra(original, 'b', 2)\n"
            "    assert new == {'a': 1, 'b': 2}\n"
            "    assert original == {'a': 1}, 'original was mutated'\n"
            "    print('ok')\n"
        ),
        fixed=(
            "def with_extra(d, k, v):\n"
            "    out = dict(d)\n"
            "    out[k] = v\n"
            "    return out\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    original = {'a': 1}\n"
            "    new = with_extra(original, 'b', 2)\n"
            "    assert new == {'a': 1, 'b': 2}\n"
            "    assert original == {'a': 1}, 'original was mutated'\n"
            "    print('ok')\n"
        ),
    ),
]


def load(limit: Optional[int] = None) -> List[BugCase]:
    """
    Return up to `limit` synthetic bug cases. Pass None for all of them.
    """
    if limit is None:
        return list(_CASES)
    return list(_CASES[:limit])


def case_ids() -> List[str]:
    return [c.bug_id for c in _CASES]
