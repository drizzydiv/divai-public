# divAI Project

## What This Is

divAI is a custom-branded wrapper around the `@anthropic-ai/claude-code` CLI. It routes requests through a local LiteLLM proxy instead of Anthropic's API directly, allowing different models to be used under the hood.

## Architecture

- **LiteLLM proxy** (`litellm_config.yaml`) runs locally on `http://127.0.0.1:4000` and maps custom model names to real provider endpoints
- **Claude Code binary** (`node_modules/@anthropic-ai/claude-code/bin/claude.exe`) is the CLI being rebranded
- **Launcher** (`start_divai.ps1`) sets env vars to point the CLI at the local proxy and launches it
- **Patch scripts** hex-edit the binary to apply branding and color changes

## Custom Models (LiteLLM)

| Model Name | Actual Model | Provider |
|---|---|---|
| `divtalk` | `llama-3.3-70b-versatile` | Groq |
| `divcode` | `gemini-2.5-flash` | Google Gemini |
| `divbrain` | `deepseek-reasoner` | DeepSeek |
| `claude-haiku-4-5-20251001` | `gemini-2.5-flash` | Google Gemini (fallback) |

## Patch Scripts

- `patch_binary.py` — replaces `"Claude Code"` with `"divAI      "` in the binary (padded to preserve offsets)
- `patch_color.py` — replaces Anthropic's terracotta `#da7756` with neon blue `#00aaff`

Both scripts have hardcoded paths pointing to the local install. Update the `exe_path` variable if the project moves.

## Running divAI

```powershell
.\start_divai.ps1
```

This sets a dummy Anthropic API key (the proxy doesn't need a real one), points the base URL to the local LiteLLM proxy, and launches the patched CLI.

## Prerequisites

- LiteLLM proxy must be running on port 4000 before launching
- Node.js / npm for the `@anthropic-ai/claude-code` dependency
- Python 3 for the patch scripts

## Notes

- The dummy API key in `start_divai.ps1` is intentional — the proxy intercepts all requests before they reach Anthropic
- Binary patches must be re-applied after `npm install` updates the package
- Padding in `patch_binary.py` is required to avoid shifting binary offsets and corrupting the executable
