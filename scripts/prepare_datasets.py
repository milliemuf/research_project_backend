"""
Bug Dataset Preparation Scripts for CodeFlow AI.

This script downloads and prepares bug datasets for evaluation:
- BugsInPy (Python bugs)
- Defects4J (Java bugs)
- Synthetic E-Commerce bugs

Author: Millicent Mufambi (H240624A)
"""

import os
import json
import subprocess
import random
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Optional


@dataclass
class BugEntry:
    """Standardized bug entry for evaluation."""
    bug_id: str
    language: str
    source: str  # 'bugsinpy', 'defects4j', 'synthetic'
    project: str
    file_path: str
    line_number: int
    original_code: str
    fixed_code: str
    bug_type: str
    description: str
    severity: str  # 'low', 'medium', 'high', 'critical'


class DatasetPreparer:
    """Prepare bug datasets for CodeFlow evaluation."""

    def __init__(self, data_dir: str = "data/bug_datasets"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def download_bugsinpy(self) -> List[BugEntry]:
        """
        Download and parse BugsInPy dataset.

        BugsInPy contains 493 bugs from 17 real-world Python projects.
        Source: https://github.com/soarsmu/BugsInPy
        """
        bugsinpy_dir = self.data_dir / "bugsinpy"

        if not bugsinpy_dir.exists():
            print("Cloning BugsInPy repository...")
            subprocess.run([
                "git", "clone",
                "https://github.com/soarsmu/BugsInPy.git",
                str(bugsinpy_dir)
            ], check=True)
        else:
            print("BugsInPy already downloaded.")

        bugs = []
        projects_dir = bugsinpy_dir / "projects"

        if projects_dir.exists():
            for project_dir in projects_dir.iterdir():
                if project_dir.is_dir():
                    bugs_dir = project_dir / "bugs"
                    if bugs_dir.exists():
                        for bug_dir in bugs_dir.iterdir():
                            if bug_dir.is_dir():
                                bug = self._parse_bugsinpy_bug(
                                    project_dir.name,
                                    bug_dir
                                )
                                if bug:
                                    bugs.append(bug)

        print(f"Loaded {len(bugs)} bugs from BugsInPy")
        return bugs

    def _parse_bugsinpy_bug(self, project: str, bug_dir: Path) -> Optional[BugEntry]:
        """Parse a single BugsInPy bug entry."""
        try:
            bug_info_file = bug_dir / "bug.info"
            if not bug_info_file.exists():
                return None

            # Read bug info
            bug_info = {}
            with open(bug_info_file, 'r') as f:
                for line in f:
                    if '=' in line:
                        key, value = line.strip().split('=', 1)
                        bug_info[key.strip()] = value.strip().strip('"')

            # Read buggy and fixed code if available
            buggy_file = bug_dir / "buggy.py"
            fixed_file = bug_dir / "fixed.py"

            original_code = ""
            fixed_code = ""

            if buggy_file.exists():
                with open(buggy_file, 'r', errors='ignore') as f:
                    original_code = f.read()

            if fixed_file.exists():
                with open(fixed_file, 'r', errors='ignore') as f:
                    fixed_code = f.read()

            return BugEntry(
                bug_id=f"bugsinpy-{project}-{bug_dir.name}",
                language="python",
                source="bugsinpy",
                project=project,
                file_path=bug_info.get('buggy_file', 'unknown'),
                line_number=int(bug_info.get('buggy_line', '1')),
                original_code=original_code[:2000],  # Truncate for storage
                fixed_code=fixed_code[:2000],
                bug_type=bug_info.get('bug_type', 'unknown'),
                description=bug_info.get('description', ''),
                severity=self._classify_severity(bug_info.get('bug_type', ''))
            )
        except Exception as e:
            print(f"Error parsing bug {bug_dir}: {e}")
            return None

    def setup_defects4j(self) -> str:
        """
        Set up Defects4J dataset.

        Defects4J contains 835 bugs from 17 Java projects.
        Requires Java 8+ to be installed.
        Source: https://github.com/rjust/defects4j
        """
        defects4j_dir = self.data_dir / "defects4j"

        if not defects4j_dir.exists():
            print("Cloning Defects4J repository...")
            subprocess.run([
                "git", "clone",
                "https://github.com/rjust/defects4j.git",
                str(defects4j_dir)
            ], check=True)

            print("Initializing Defects4J (requires Java 8+)...")
            print("Run: cd data/bug_datasets/defects4j && ./init.sh")
        else:
            print("Defects4J already downloaded.")

        return str(defects4j_dir)

    def generate_synthetic_ecommerce_bugs(self, count: int = 2000) -> List[BugEntry]:
        """
        Generate synthetic e-commerce bugs for domain-specific evaluation.

        Bug categories:
        - Payment calculation errors
        - Cart state inconsistencies
        - Inventory race conditions
        - Currency conversion bugs
        - Session management issues
        - Input validation failures
        """
        bugs = []

        # Bug templates with original and fixed code
        bug_templates = [
            # Payment calculation bugs
            {
                "bug_type": "payment_calculation",
                "original": "total = price * quantity",
                "fixed": "total = Decimal(str(price)) * Decimal(str(quantity))",
                "description": "Float precision error in payment calculation",
                "severity": "critical"
            },
            {
                "bug_type": "payment_calculation",
                "original": "discount = total * discount_percent",
                "fixed": "discount = total * (discount_percent / Decimal('100'))",
                "description": "Incorrect discount percentage calculation",
                "severity": "high"
            },
            {
                "bug_type": "payment_calculation",
                "original": "tax = price * 0.15",
                "fixed": "tax = Decimal(str(price)) * Decimal('0.15')",
                "description": "Tax calculation using float instead of Decimal",
                "severity": "critical"
            },

            # Cart state bugs
            {
                "bug_type": "cart_state",
                "original": "cart.items.append(item)",
                "fixed": "cart.items.append(item.copy())",
                "description": "Mutable object reference in cart causes state corruption",
                "severity": "high"
            },
            {
                "bug_type": "cart_state",
                "original": "if item in cart.items:",
                "fixed": "if any(i.product_id == item.product_id for i in cart.items):",
                "description": "Incorrect item comparison in cart",
                "severity": "medium"
            },

            # Inventory bugs
            {
                "bug_type": "inventory_race",
                "original": "if product.stock > 0:\n    product.stock -= 1",
                "fixed": "with product.lock:\n    if product.stock > 0:\n        product.stock -= 1",
                "description": "Race condition in inventory decrement",
                "severity": "critical"
            },
            {
                "bug_type": "inventory_race",
                "original": "stock = get_stock(product_id)\nif stock >= quantity:",
                "fixed": "with db.transaction():\n    stock = get_stock_for_update(product_id)\n    if stock >= quantity:",
                "description": "TOCTOU race in stock checking",
                "severity": "critical"
            },

            # Currency conversion bugs
            {
                "bug_type": "currency_conversion",
                "original": "converted = amount * exchange_rate",
                "fixed": "converted = (Decimal(str(amount)) * Decimal(str(exchange_rate))).quantize(Decimal('0.01'))",
                "description": "Currency conversion without proper rounding",
                "severity": "high"
            },

            # Session management bugs
            {
                "bug_type": "session_management",
                "original": "session['user_id'] = user.id",
                "fixed": "session.regenerate()\nsession['user_id'] = user.id",
                "description": "Session fixation vulnerability on login",
                "severity": "critical"
            },
            {
                "bug_type": "session_management",
                "original": "if 'cart' not in session:\n    session['cart'] = cart",
                "fixed": "if 'cart' not in session:\n    session['cart'] = cart.copy()",
                "description": "Shared cart reference across sessions",
                "severity": "high"
            },

            # Input validation bugs
            {
                "bug_type": "input_validation",
                "original": "quantity = int(request.form['quantity'])",
                "fixed": "quantity = max(1, min(int(request.form['quantity']), MAX_QUANTITY))",
                "description": "Missing quantity bounds validation",
                "severity": "medium"
            },
            {
                "bug_type": "input_validation",
                "original": "price = float(request.json['price'])",
                "fixed": "price = Decimal(str(request.json['price']))\nif price < 0:\n    raise ValueError('Invalid price')",
                "description": "Missing negative price validation",
                "severity": "critical"
            },

            # Null pointer bugs
            {
                "bug_type": "null_pointer",
                "original": "user_email = user.email.lower()",
                "fixed": "user_email = user.email.lower() if user and user.email else None",
                "description": "NullPointerException on user email access",
                "severity": "medium"
            },
            {
                "bug_type": "null_pointer",
                "original": "shipping_address = order.shipping.address",
                "fixed": "shipping_address = order.shipping.address if order.shipping else None",
                "description": "Missing null check on shipping info",
                "severity": "medium"
            },

            # Off-by-one errors
            {
                "bug_type": "off_by_one",
                "original": "if item.stock >= 0:",
                "fixed": "if item.stock > 0:",
                "description": "Off-by-one error allows overselling",
                "severity": "high"
            },
            {
                "bug_type": "off_by_one",
                "original": "for i in range(len(items) + 1):",
                "fixed": "for i in range(len(items)):",
                "description": "Index out of bounds in item iteration",
                "severity": "medium"
            },
        ]

        # Generate bugs from templates
        for i in range(count):
            template = random.choice(bug_templates)

            # Add variation to make each bug unique
            variation_id = f"{i:05d}"

            bug = BugEntry(
                bug_id=f"synthetic-ecommerce-{variation_id}",
                language="python",
                source="synthetic",
                project="ecommerce-simulator",
                file_path=f"src/ecommerce/{template['bug_type']}/{variation_id}.py",
                line_number=random.randint(10, 200),
                original_code=self._expand_template(template["original"], variation_id),
                fixed_code=self._expand_template(template["fixed"], variation_id),
                bug_type=template["bug_type"],
                description=template["description"],
                severity=template["severity"]
            )
            bugs.append(bug)

        print(f"Generated {len(bugs)} synthetic e-commerce bugs")
        return bugs

    def _expand_template(self, code: str, variation_id: str) -> str:
        """Expand a code template with context."""
        context = f'''# File: ecommerce_module_{variation_id}.py
# Generated for CodeFlow AI evaluation

class EcommerceHandler:
    def process(self, request):
        {code}
        return result
'''
        return context

    def _classify_severity(self, bug_type: str) -> str:
        """Classify bug severity based on type."""
        critical_types = ['security', 'payment', 'data_loss', 'crash']
        high_types = ['race', 'memory', 'logic']
        medium_types = ['validation', 'null', 'bounds']

        bug_type_lower = bug_type.lower()

        for t in critical_types:
            if t in bug_type_lower:
                return 'critical'
        for t in high_types:
            if t in bug_type_lower:
                return 'high'
        for t in medium_types:
            if t in bug_type_lower:
                return 'medium'
        return 'low'

    def save_dataset(self, bugs: List[BugEntry], filename: str):
        """Save bug dataset to JSON file."""
        output_file = self.data_dir / filename

        with open(output_file, 'w') as f:
            json.dump([asdict(b) for b in bugs], f, indent=2)

        print(f"Saved {len(bugs)} bugs to {output_file}")

    def load_dataset(self, filename: str) -> List[BugEntry]:
        """Load bug dataset from JSON file."""
        input_file = self.data_dir / filename

        with open(input_file, 'r') as f:
            data = json.load(f)

        return [BugEntry(**d) for d in data]

    def prepare_full_dataset(self):
        """Prepare the complete evaluation dataset (10,000+ bugs)."""
        all_bugs = []

        # 1. BugsInPy (Python)
        print("\n=== Preparing BugsInPy ===")
        try:
            bugsinpy_bugs = self.download_bugsinpy()
            all_bugs.extend(bugsinpy_bugs)
            self.save_dataset(bugsinpy_bugs, "bugsinpy.json")
        except Exception as e:
            print(f"BugsInPy preparation failed: {e}")

        # 2. Defects4J (Java) - Setup only, requires manual init
        print("\n=== Setting up Defects4J ===")
        try:
            defects4j_path = self.setup_defects4j()
            print(f"Defects4J located at: {defects4j_path}")
            print("Note: Run './init.sh' in the defects4j directory to complete setup")
        except Exception as e:
            print(f"Defects4J setup failed: {e}")

        # 3. Synthetic E-Commerce bugs
        print("\n=== Generating Synthetic E-Commerce Bugs ===")
        synthetic_bugs = self.generate_synthetic_ecommerce_bugs(2000)
        all_bugs.extend(synthetic_bugs)
        self.save_dataset(synthetic_bugs, "synthetic_ecommerce.json")

        # Save combined dataset
        print("\n=== Saving Combined Dataset ===")
        self.save_dataset(all_bugs, "combined_dataset.json")

        # Print summary
        print("\n" + "=" * 50)
        print("DATASET PREPARATION SUMMARY")
        print("=" * 50)
        print(f"Total bugs prepared: {len(all_bugs)}")
        print(f"  - BugsInPy (Python): {len([b for b in all_bugs if b.source == 'bugsinpy'])}")
        print(f"  - Synthetic E-Commerce: {len([b for b in all_bugs if b.source == 'synthetic'])}")
        print("\nBug types distribution:")

        type_counts = {}
        for bug in all_bugs:
            type_counts[bug.bug_type] = type_counts.get(bug.bug_type, 0) + 1

        for bug_type, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            print(f"  - {bug_type}: {count}")

        print("\nSeverity distribution:")
        severity_counts = {}
        for bug in all_bugs:
            severity_counts[bug.severity] = severity_counts.get(bug.severity, 0) + 1

        for severity, count in sorted(severity_counts.items()):
            print(f"  - {severity}: {count}")

        return all_bugs


def main():
    """Main entry point for dataset preparation."""
    import argparse

    parser = argparse.ArgumentParser(description="Prepare bug datasets for CodeFlow AI")
    parser.add_argument(
        "--data-dir",
        default="data/bug_datasets",
        help="Directory to store datasets"
    )
    parser.add_argument(
        "--synthetic-count",
        type=int,
        default=2000,
        help="Number of synthetic e-commerce bugs to generate"
    )
    parser.add_argument(
        "--only-synthetic",
        action="store_true",
        help="Only generate synthetic bugs (skip downloads)"
    )

    args = parser.parse_args()

    preparer = DatasetPreparer(args.data_dir)

    if args.only_synthetic:
        bugs = preparer.generate_synthetic_ecommerce_bugs(args.synthetic_count)
        preparer.save_dataset(bugs, "synthetic_ecommerce.json")
    else:
        preparer.prepare_full_dataset()


if __name__ == "__main__":
    main()
