# CodeFlow AI

**Byzantine Fault-Tolerant Multi-Agent System for Autonomous Runtime Program Repair**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Research Project

**Author:** Millicent Mufambi (H240624A)
**Degree:** M.Tech Software Engineering, Harare Institute of Technology
**Supervisor:** Mr Makondo
**Timeline:** Nov 2025 - Jul 2026

## Overview

CodeFlow AI is a novel system that combines **Byzantine Fault Tolerance (BFT)** with **Automated Program Repair (APR)** using a multi-agent consensus mechanism. This is the first system to apply formal Byzantine consensus protocols to automated code repair, targeting 95%+ reliability for production e-commerce systems.

### Key Innovation

Traditional automated repair systems achieve 27-45% accuracy with no safety guarantees. CodeFlow AI introduces:

1. **Heterogeneous Multi-Agent Architecture**: Diverse LLM-powered agents (Claude, GPT-4, Ollama) reduce correlated failures
2. **PBFT Consensus**: Formal Byzantine fault tolerance guarantees with 3f+1 agents
3. **Runtime Repair**: Production-time bug detection and autonomous fixing
4. **E-Commerce Focus**: Domain-specific bug patterns for financial system safety

## Architecture

```
                    ┌──────────────────────────────────────┐
                    │         Vue.js Dashboard             │
                    │   (Real-time Consensus Monitoring)   │
                    └─────────────────┬────────────────────┘
                                      │
                    ┌─────────────────▼────────────────────┐
                    │           FastAPI Gateway            │
                    │    (REST API + WebSocket Server)     │
                    └─────────────────┬────────────────────┘
                                      │
        ┌─────────────────────────────┼─────────────────────────────┐
        │                             │                             │
┌───────▼───────┐           ┌────────▼────────┐           ┌────────▼────────┐
│   ANALYZER    │           │     HEALER      │           │    VALIDATOR    │
│    Agent      │           │     Agent       │           │      Agent      │
│               │           │                 │           │                 │
│  Claude API   │           │   GPT-4 API     │           │  Ollama/Local   │
│               │           │                 │           │                 │
│ Bug Detection │           │ Fix Generation  │           │ Fix Verification│
└───────┬───────┘           └────────┬────────┘           └────────┬────────┘
        │                            │                             │
        └────────────────────────────┼─────────────────────────────┘
                                     │
                    ┌────────────────▼─────────────────┐
                    │       PBFT CONSENSUS ENGINE      │
                    │  (Byzantine Fault Tolerant)      │
                    │                                  │
                    │  Pre-Prepare → Prepare → Commit  │
                    └────────────────┬─────────────────┘
                                     │
                    ┌────────────────▼─────────────────┐
                    │        Knowledge Graph           │
                    │     (Bug Pattern Learning)       │
                    └──────────────────────────────────┘
```

## PBFT Consensus Protocol

The core research contribution - adapting Practical Byzantine Fault Tolerance for code repair:

- **Fault Tolerance**: System tolerates f faulty/malicious agents
- **Agent Requirement**: Minimum 3f+1 agents (4 agents for f=1)
- **Quorum**: 2f+1 agreements required for consensus

### Consensus Phases

1. **Pre-Prepare**: Primary agent proposes a fix candidate
2. **Prepare**: All agents validate and broadcast readiness
3. **Commit**: 2f+1 agreements trigger fix deployment

## Project Structure

```
codeflow-backend/
├── app/
│   ├── main.py                 # FastAPI entry point
│   ├── config.py               # Configuration management
│   │
│   ├── agents/                 # Multi-Agent System
│   │   ├── base_agent.py       # Abstract agent class
│   │   ├── analyzer_agent.py   # Bug detection (Claude)
│   │   ├── healer_agent.py     # Fix generation (GPT-4)
│   │   ├── validator_agent.py  # Fix verification (Ollama)
│   │   └── agent_manager.py    # Agent orchestration
│   │
│   ├── consensus/              # PBFT Implementation
│   │   ├── pbft.py             # Core PBFT consensus
│   │   ├── message_types.py    # Consensus messages
│   │   ├── crypto.py           # Cryptographic signing
│   │   └── state_machine.py    # State management
│   │
│   ├── api/                    # REST API
│   │   ├── routes/
│   │   │   ├── bugs.py
│   │   │   ├── fixes.py
│   │   │   ├── agents.py
│   │   │   └── dashboard.py
│   │   └── websockets.py       # Real-time updates
│   │
│   └── models/                 # Data models
│
├── tests/
│   ├── unit/
│   │   └── test_pbft_consensus.py
│   ├── integration/
│   └── benchmarks/
│
├── scripts/
│   └── prepare_datasets.py     # Bug dataset preparation
│
├── data/
│   └── bug_datasets/           # Evaluation datasets
│
├── docs/
│   └── OLLAMA_SETUP.md         # Ollama configuration guide
│
├── requirements.txt
├── pyproject.toml
└── .env                        # Environment configuration
```

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 15+
- Redis 7+
- Ollama (for local validation)

### Installation

1. **Clone and setup virtual environment:**
```bash
cd codeflow-backend
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac
```

2. **Install dependencies:**
```bash
pip install -r requirements.txt
```

3. **Configure environment:**
```bash
# Copy example and edit with your API keys
copy .env.example .env
```

4. **Setup Ollama (free local LLM):**
```bash
# Download from https://ollama.ai/download
ollama pull codellama:7b
ollama serve
```

5. **Run the server:**
```bash
uvicorn app.main:app --reload
```

### API Documentation

Once running, access:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Configuration

### Environment Variables

```env
# LLM API Keys
ANTHROPIC_API_KEY=your_claude_key
OPENAI_API_KEY=your_openai_key
OLLAMA_BASE_URL=http://localhost:11434

# Database
DATABASE_URL=postgresql+asyncpg://localhost/codeflow
REDIS_URL=redis://localhost:6379/0

# PBFT Configuration
PBFT_FAULT_TOLERANCE=1          # f value
CONSENSUS_TIMEOUT_MS=5000       # Timeout per round
MIN_AGENTS_FOR_CONSENSUS=4      # 3f+1
```

## Evaluation

### Bug Datasets

The system is evaluated on 10,000+ bugs:
- **BugsInPy**: 493 real Python bugs
- **Defects4J**: 835 real Java bugs
- **Synthetic**: 2,000+ e-commerce-specific bugs

### Prepare Datasets

```bash
python scripts/prepare_datasets.py
```

### Run Tests

```bash
# Unit tests
pytest tests/unit/ -v

# PBFT consensus tests
pytest tests/unit/test_pbft_consensus.py -v

# Integration tests
pytest tests/integration/ -v
```

### Target Metrics

| Metric | Target | Description |
|--------|--------|-------------|
| Repair Accuracy | ≥95% | Correct fixes / Total bugs |
| Consensus Latency | <500ms | Time to reach consensus |
| Safety Rate | 100% | Zero catastrophic failures |
| False Positive Rate | <5% | Incorrect bug detections |

## Frontend

The Vue.js frontend is located at: `C:\dev\frontend\Mtech_Project_Frontend`

Features:
- Real-time consensus visualization
- Agent health monitoring
- Bug tracking dashboard
- Fix history and metrics

## Research Contributions

1. **Novel H-BFT Algorithm**: Heterogeneous Byzantine Fault Tolerance for diverse AI agents
2. **First BFT+APR Integration**: Formal consensus guarantees for automated repair
3. **Multi-LLM Diversity**: Uncorrelated failures through model heterogeneity
4. **E-Commerce Domain Adaptation**: Specialized bug patterns for financial systems

## Publications

Target venues:
- ICSE (International Conference on Software Engineering)
- ASE (Automated Software Engineering)
- IEEE TSE (Transactions on Software Engineering)

## License

MIT License - See LICENSE file for details.

## Acknowledgments

- Harare Institute of Technology
- Supervisor: Mr Makondo
- Research funding: [Your funding source]

## Contact

Millicent Mufambi
H240624A
M.Tech Software Engineering
Harare Institute of Technology
