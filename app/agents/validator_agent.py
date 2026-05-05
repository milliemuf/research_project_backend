"""
Validator Agent - Fix Verification.

This agent is responsible for:
1. Validating proposed fixes for correctness
2. Checking for safety issues
3. Running static analysis
4. Simulating fix execution

Uses Ollama (local LLM) for fast, free validation.

Author: Millicent Mufambi (H240624A)
"""

from dataclasses import dataclass
from typing import Optional, List
from datetime import datetime
import json
import re
import ast

from app.agents.base_agent import BaseAgent, AgentConfig, AgentOutput, AgentType, LLMProvider
from app.agents.healer_agent import FixCandidate
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class ValidationInput:
    """Input for fix validation."""
    original_code: str
    fix_candidate: FixCandidate
    language: str
    file_path: str
    test_cases: Optional[List[str]] = None


@dataclass
class ValidationResult:
    """Result of fix validation."""
    is_valid: bool
    confidence: float
    syntax_valid: bool
    safety_score: float
    issues: List[str]
    recommendations: List[str]
    test_results: Optional[dict] = None


class ValidatorAgent(BaseAgent):
    """
    Validator Agent for verifying proposed fixes.

    This agent validates fixes before they are applied:
    - Syntax checking
    - Static analysis
    - Safety verification
    - (Optional) Test execution

    Uses Ollama for fast, local validation without API costs.
    """

    # Dangerous patterns to check for
    DANGEROUS_PATTERNS = [
        (r'\beval\s*\(', "Use of eval() is dangerous"),
        (r'\bexec\s*\(', "Use of exec() is dangerous"),
        (r'__import__\s*\(', "Dynamic imports are risky"),
        (r'\bos\.system\s*\(', "Shell command execution"),
        (r'\bsubprocess\.(call|run|Popen)', "Subprocess execution"),
        (r'open\s*\([^)]*["\']w', "File write operation"),
        (r'\brm\s+-rf', "Destructive file operation"),
    ]

    def __init__(self, config: Optional[AgentConfig] = None):
        if config is None:
            config = AgentConfig(
                agent_id="validator-ollama-01",
                agent_type=AgentType.VALIDATOR,
                llm_provider=LLMProvider.OLLAMA,
                model_name="http://localhost:11434",
                temperature=0.1,  # Low temperature for consistent validation
                max_tokens=1024,
            )
        super().__init__(config)

    async def process(self, input_data: ValidationInput) -> AgentOutput:
        """
        Validate a proposed fix.

        Args:
            input_data: Fix candidate and context

        Returns:
            AgentOutput containing ValidationResult
        """
        start_time = datetime.utcnow()

        try:
            # Step 1: Static checks (no LLM needed)
            static_result = self._static_validation(input_data)

            # Step 2: LLM-based semantic validation
            if static_result.syntax_valid:
                prompt = self._build_prompt(input_data)
                llm_response = await self._call_llm(prompt)
                semantic_result = self._parse_response(llm_response)

                # Combine results
                result = ValidationResult(
                    is_valid=static_result.is_valid and semantic_result.is_valid,
                    confidence=(static_result.confidence + semantic_result.confidence) / 2,
                    syntax_valid=static_result.syntax_valid,
                    safety_score=static_result.safety_score,
                    issues=static_result.issues + semantic_result.issues,
                    recommendations=semantic_result.recommendations,
                )
            else:
                result = static_result

            latency = (datetime.utcnow() - start_time).total_seconds() * 1000

            self.update_reputation(True)

            logger.info(
                "Fix validated",
                agent_id=self.agent_id,
                is_valid=result.is_valid,
                confidence=result.confidence,
                issues=len(result.issues),
                latency_ms=latency
            )

            return AgentOutput(
                agent_id=self.agent_id,
                agent_type=self.agent_type,
                success=True,
                result=result,
                confidence=result.confidence,
                reasoning="; ".join(result.issues) if result.issues else "Fix looks valid",
                latency_ms=latency,
            )

        except Exception as e:
            latency = (datetime.utcnow() - start_time).total_seconds() * 1000
            self.update_reputation(False)

            logger.error("Validation failed", error=str(e))

            return AgentOutput(
                agent_id=self.agent_id,
                agent_type=self.agent_type,
                success=False,
                result=ValidationResult(
                    is_valid=False,
                    confidence=0.0,
                    syntax_valid=False,
                    safety_score=0.0,
                    issues=[f"Validation error: {str(e)}"],
                    recommendations=["Manual review required"]
                ),
                confidence=0.0,
                reasoning=f"Validation failed: {str(e)}",
                latency_ms=latency,
            )

    def _static_validation(self, input_data: ValidationInput) -> ValidationResult:
        """Perform static validation without LLM."""
        issues = []
        safety_score = 1.0

        fixed_code = input_data.fix_candidate.fixed_code

        # Check syntax (for Python)
        syntax_valid = True
        if input_data.language.lower() == "python":
            try:
                ast.parse(fixed_code)
            except SyntaxError as e:
                syntax_valid = False
                issues.append(f"Syntax error: {e.msg} at line {e.lineno}")

        # Check for dangerous patterns
        for pattern, description in self.DANGEROUS_PATTERNS:
            if re.search(pattern, fixed_code):
                issues.append(f"Safety issue: {description}")
                safety_score -= 0.2

        # Check if fix is actually different from original
        if fixed_code.strip() == input_data.original_code.strip():
            issues.append("Fix is identical to original code")

        # Clamp safety score
        safety_score = max(0.0, safety_score)

        is_valid = syntax_valid and safety_score >= 0.5 and \
                   fixed_code.strip() != input_data.original_code.strip()

        return ValidationResult(
            is_valid=is_valid,
            confidence=0.7 if is_valid else 0.3,
            syntax_valid=syntax_valid,
            safety_score=safety_score,
            issues=issues,
            recommendations=[],
        )

    def _build_prompt(self, input_data: ValidationInput) -> str:
        """Build the validation prompt for the LLM."""
        return f"""You are a code reviewer validating a bug fix.
Analyze if this fix is correct and safe.

## Original Code
```{input_data.language}
{input_data.original_code}
```

## Proposed Fix
```{input_data.language}
{input_data.fix_candidate.fixed_code}
```

## Fix Explanation
{input_data.fix_candidate.explanation}

## Your Task
Validate this fix and respond with JSON:
{{
    "is_valid": <true/false>,
    "confidence": <0.0-1.0>,
    "issues": ["<list any issues found>"],
    "recommendations": ["<suggestions for improvement>"]
}}

Consider:
1. Does the fix actually address the bug?
2. Are there any edge cases not handled?
3. Could the fix introduce new bugs?
4. Is the fix consistent with the codebase style?

Respond ONLY with the JSON object."""

    def _parse_response(self, response: str) -> ValidationResult:
        """Parse LLM validation response."""
        json_match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
        if json_match:
            response = json_match.group()

        try:
            data = json.loads(response)
            return ValidationResult(
                is_valid=data.get("is_valid", False),
                confidence=float(data.get("confidence", 0.5)),
                syntax_valid=True,  # Already checked in static
                safety_score=1.0,  # Already checked in static
                issues=data.get("issues", []),
                recommendations=data.get("recommendations", []),
            )
        except json.JSONDecodeError:
            return ValidationResult(
                is_valid=False,
                confidence=0.3,
                syntax_valid=True,
                safety_score=1.0,
                issues=["Could not parse validation response"],
                recommendations=["Manual review recommended"],
            )
