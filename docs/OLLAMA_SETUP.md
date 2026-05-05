# Ollama Setup Guide for CodeFlow AI

This guide explains how to set up Ollama for the Validator Agent, enabling **free, local LLM inference** for fix verification.

## Why Ollama?

The CodeFlow multi-agent system uses heterogeneous LLMs:
- **Analyzer Agent**: Claude API (best code understanding)
- **Healer Agent**: GPT-4 API (strong code generation)
- **Validator Agent**: Ollama/Llama (free, local, fast)

Using Ollama for validation provides:
- **Zero API costs** for validation checks
- **No rate limits** during evaluation
- **Privacy** - code never leaves your machine
- **Speed** - no network latency

## Installation

### Windows

1. Download Ollama from: https://ollama.ai/download/windows

2. Run the installer and follow prompts

3. Verify installation:
```bash
ollama --version
```

### Linux

```bash
curl -fsSL https://ollama.ai/install.sh | sh
```

### macOS

```bash
brew install ollama
```

Or download from: https://ollama.ai/download/mac

## Recommended Models

### For Code Validation (Recommended)

**CodeLlama 7B** - Optimized for code understanding:
```bash
ollama pull codellama:7b
```

**Llama 3 8B** - Good general reasoning:
```bash
ollama pull llama3:8b
```

### For Resource-Constrained Systems

**CodeLlama 7B Quantized** - Lower memory usage:
```bash
ollama pull codellama:7b-instruct-q4_0
```

**Phi-2** - Very lightweight (2.7B parameters):
```bash
ollama pull phi
```

### Model Comparison

| Model | Size | VRAM Required | Speed | Code Quality |
|-------|------|---------------|-------|--------------|
| codellama:7b | 3.8GB | 8GB | Fast | Excellent |
| llama3:8b | 4.7GB | 8GB | Fast | Good |
| codellama:13b | 7.4GB | 16GB | Medium | Best |
| phi | 1.7GB | 4GB | Fastest | Adequate |

## Configuration

### 1. Start Ollama Server

```bash
# Start the Ollama service
ollama serve
```

The server runs on `http://localhost:11434` by default.

### 2. Configure CodeFlow

Update your `.env` file:
```env
# Ollama Configuration
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=codellama:7b

# Optional: Custom timeout for large code analysis
OLLAMA_TIMEOUT=120
```

### 3. Test Connection

```python
# test_ollama.py
import requests

response = requests.post(
    "http://localhost:11434/api/generate",
    json={
        "model": "codellama:7b",
        "prompt": "def add(a, b):",
        "stream": False
    }
)

print(response.json()["response"])
```

## Validator Agent Integration

The Validator Agent uses Ollama for fix verification:

```python
# Example validation prompt
VALIDATION_PROMPT = """
Analyze this code fix for correctness and safety.

Original Code (Buggy):
```python
{original_code}
```

Proposed Fix:
```python
{fixed_code}
```

Bug Type: {bug_type}
Fix Explanation: {explanation}

Evaluate:
1. Does the fix address the reported bug?
2. Are there any new bugs introduced?
3. Is the fix safe for production?
4. Confidence score (0.0-1.0)?

Respond in JSON format:
{{
    "is_valid": true/false,
    "confidence": 0.0-1.0,
    "reasoning": "...",
    "potential_issues": []
}}
"""
```

## Performance Tuning

### GPU Acceleration (Recommended)

Ollama automatically uses GPU if available. For NVIDIA GPUs:

1. Install CUDA drivers
2. Verify GPU detection:
```bash
ollama run codellama:7b "Hello"
# Check logs for GPU usage
```

### CPU-Only Mode

For systems without GPU:
```bash
# Use quantized models
ollama pull codellama:7b-instruct-q4_0

# Set CPU threads (optional)
export OLLAMA_NUM_PARALLEL=4
```

### Memory Management

```bash
# Reduce context window for lower memory
export OLLAMA_NUM_CTX=2048

# Limit parallel requests
export OLLAMA_NUM_PARALLEL=1
```

## Troubleshooting

### Connection Refused

```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Restart Ollama
# Windows: Restart from system tray
# Linux: sudo systemctl restart ollama
```

### Out of Memory

1. Use a smaller model:
```bash
ollama pull phi  # Only 1.7GB
```

2. Reduce context window:
```bash
export OLLAMA_NUM_CTX=1024
```

3. Close other applications

### Slow Performance

1. Enable GPU acceleration (see above)
2. Use quantized models (q4_0 variants)
3. Reduce concurrent requests

## API Reference

### Generate Response

```bash
curl http://localhost:11434/api/generate -d '{
  "model": "codellama:7b",
  "prompt": "Explain this code: def factorial(n):",
  "stream": false
}'
```

### List Models

```bash
curl http://localhost:11434/api/tags
```

### Pull Model

```bash
curl http://localhost:11434/api/pull -d '{
  "name": "codellama:7b"
}'
```

## Integration Test

Run the Ollama integration test:

```bash
cd codeflow-backend
python -m pytest tests/integration/test_ollama.py -v
```

Expected output:
```
test_ollama_connection ... PASSED
test_code_generation ... PASSED
test_validation_prompt ... PASSED
```

## Resources

- Ollama Documentation: https://github.com/ollama/ollama
- Model Library: https://ollama.ai/library
- CodeLlama Paper: https://arxiv.org/abs/2308.12950
- Llama 3 Paper: https://ai.meta.com/llama/

## Support

For issues with Ollama setup:
1. Check Ollama GitHub Issues: https://github.com/ollama/ollama/issues
2. Verify system requirements (RAM, disk space)
3. Try a smaller model first

For CodeFlow integration issues:
1. Verify `.env` configuration
2. Check Ollama is running (`curl localhost:11434`)
3. Review Validator Agent logs
