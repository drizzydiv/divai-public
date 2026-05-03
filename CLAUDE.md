# divAI Context File

divAI is a custom-branded wrapper around `@anthropic-ai/claude-code` that routes through a local LiteLLM proxy, enabling different models under the hood.

## Quick Start

1. Start the LiteLLM proxy on port 4000
2. Run `.\start_divai.ps1` to launch the patched CLI

## Models

| Name | Model | Provider |
|---|---|---|
| `divtalk` | llama-3.3-70b-versatile | Groq |
| `divcode` | gemini-2.5-flash | Gemini |
| `divbrain` | deepseek-reasoner | DeepSeek |

## After `npm install`

Re-run both patch scripts to restore branding:

```powershell
python patch_binary.py
python patch_color.py
```

## Key Files

- `litellm_config.yaml` — proxy model routing config
- `start_divai.ps1` — launcher (sets dummy API key + base URL)
- `patch_binary.py` — renames "Claude Code" → "divAI" in binary
- `patch_color.py` — changes accent color to neon blue `#00aaff`
