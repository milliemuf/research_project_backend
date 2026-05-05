"""
Analyzer Agent - Bug Detection and Classification.

This agent is responsible for:
1. Analyzing runtime errors and exceptions
2. Classifying bug types (null pointer, type error, etc.)
3. Extracting relevant code context
4. Assessing bug severity

Uses Claude API for deep code understanding.

Author: Millicent Mufambi (H240624A)
"""

from dataclasses import dataclass
from typing import Optional, List
from datetime import datetime
import json
import re

from app.agents.base_agent import BaseAgent, AgentConfig, AgentOutput, AgentType, LLMProvider
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class BugAnalysisInput:
    """Input for bug analysis."""
    error_message: str
    stack_trace: str
    code_context: str
    file_path: str
    line_number: int
    language: str = "python"
    additional_context: Optional[dict] = None


@dataclass
class BugAnalysisResult:
    """Result of bug analysis."""
    bug_type: str
    severity: str  # critical, high, medium, low
    root_cause: str
    affected_code: str
    suggested_approach: str
    related_patterns: List[str]


class AnalyzerAgent(BaseAgent):
    """
    Analyzer Agent for bug detection and classification.

    This agent specializes in understanding code errors and determining:
    - What type of bug occurred
    - Why it happened (root cause analysis)
    - How severe the bug is
    - What approach should be taken to fix it

    Typically uses Claude API for its strong code understanding capabilities.
    """

    BUG_TYPES = [
        "null_pointer",
        "type_error",
        "index_out_of_bounds",
        "division_by_zero",
        "api_error",
        "timeout",
        "memory_error",
        "syntax_error",
        "logic_error",
        "concurrency_error",
        "unknown"
    ]

    SEVERITY_LEVELS = ["critical", "high", "medium", "low"]

    def __init__(self, config: Optional[AgentConfig] = None):
        if config is None:
            config = AgentConfig(
                agent_id="analyzer-claude-01",
                agent_type=AgentType.ANALYZER,
                llm_provider=LLMProvider.CLAUDE,
                model_name="claude-3-sonnet-20240229",
                temperature=0.3,  # Lower temperature for analysis
            )
        super().__init__(config)

    async def process(self, input_data: BugAnalysisInput) -> AgentOutput:
        """
        Analyze a bug and classify it.

        Args:
            input_data: Bug information including error message and context

        Returns:
            AgentOutput containing BugAnalysisResult
        """
        start_time = datetime.utcnow()

        try:
            prompt = self._build_prompt(input_data)
            llm_response = await self._call_llm(prompt)
            result = self._parse_response(llm_response)

            latency = (datetime.utcnow() - start_time).total_seconds() * 1000

            self.update_reputation(True)

            logger.info(
                "Bug analyzed",
                agent_id=self.agent_id,
                bug_type=result.bug_type,
                severity=result.severity,
                latency_ms=latency
            )

            return AgentOutput(
                agent_id=self.agent_id,
                agent_type=self.agent_type,
                success=True,
                result=result,
                confidence=self._calculate_confidence(result),
                reasoning=result.root_cause,
                latency_ms=latency,
                metadata={
                    "file_path": input_data.file_path,
                    "line_number": input_data.line_number,
                    "language": input_data.language,
                }
            )

        except Exception as e:
            latency = (datetime.utcnow() - start_time).total_seconds() * 1000
            self.update_reputation(False)

            logger.error("Bug analysis failed", error=str(e))

            return AgentOutput(
                agent_id=self.agent_id,
                agent_type=self.agent_type,
                success=False,
                result=None,
                confidence=0.0,
                reasoning=f"Analysis failed: {str(e)}",
                latency_ms=latency,
            )

    def _build_prompt(self, input_data: BugAnalysisInput) -> str:
        """Build the analysis prompt for the LLM."""
        return f"""You are an expert software engineer analyzing a runtime error.
Analyze the following bug and provide a structured analysis.

## Error Information
**Error Message:** {input_data.error_message}

**File:** {input_data.file_path}
**Line:** {input_data.line_number}
**Language:** {input_data.language}

## Stack Trace
```
{input_data.stack_trace}
```

## Code Context
```{input_data.language}
{input_data.code_context}
```

## Your Task
Provide a JSON response with the following structure:
{{
    "bug_type": "<one of: {', '.join(self.BUG_TYPES)}>",
    "severity": "<one of: {', '.join(self.SEVERITY_LEVELS)}>",
    "root_cause": "<brief explanation of why this error occurred>",
    "affected_code": "<the specific code causing the issue>",
    "suggested_approach": "<how to fix this bug>",
    "related_patterns": ["<list of similar bug patterns>"]
}}

Respond ONLY with the JSON object, no additional text."""

    def _parse_response(self, response: str) -> BugAnalysisResult:
        """Parse the LLM response into a structured result."""
        # Extract JSON from response (handle markdown code blocks)
        json_match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
        if json_match:
            response = json_match.group()

        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            # Fallback to default values
            return BugAnalysisResult(
                bug_type="unknown",
                severity="medium",
                root_cause="Unable to determine root cause",
                affected_code="",
                suggested_approach="Manual investigation required",
                related_patterns=[]
            )

        return BugAnalysisResult(
            bug_type=data.get("bug_type", "unknown"),
            severity=data.get("severity", "medium"),
            root_cause=data.get("root_cause", ""),
            affected_code=data.get("affected_code", ""),
            suggested_approach=data.get("suggested_approach", ""),
            related_patterns=data.get("related_patterns", [])
        )

    def _calculate_confidence(self, result: BugAnalysisResult) -> float:
        """Calculate confidence score based on analysis quality."""
        confidence = 0.5  # Base confidence

        # Known bug type increases confidence
        if result.bug_type in self.BUG_TYPES and result.bug_type != "unknown":
            confidence += 0.2

        # Detailed root cause increases confidence
        if len(result.root_cause) > 20:
            confidence += 0.1

        # Suggested approach increases confidence
        if len(result.suggested_approach) > 20:
            confidence += 0.1

        # Related patterns increases confidence
        if len(result.related_patterns) > 0:
            confidence += 0.1

        return min(confidence, 1.0)
