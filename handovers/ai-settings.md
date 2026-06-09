# AI settings (your own API key)

**Status: ✅ Live.**

## What it does (AI Context tab)
Edit the LLM provider + your own API key from the dashboard (no Django admin):
- **Provider** dropdown (OpenAI / Anthropic / Google / Groq / Mistral / Cohere / OpenAI-compatible).
- **API key** (password field; masked on load — only replaced when you type a new one).
- **Model** (e.g. claude-sonnet-4-6) and **API base** (for OpenAI-compatible).
- Plus the **AI Context** free-text (what you sell / ideal lead) that drives scoring, search-keyword generation, and message personalisation.
- The **Slack notifications** section also lives on this tab (see slack-notifications.md).

Backed by `SiteConfig` (llm_provider/llm_api_key/ai_model/llm_api_base/ai_context). The worker reads these
for lead scoring, AI search, and follow-up generation.

## Key files
`linkedin/models.py` (SiteConfig), `linkedin/llm.py` (`get_llm_model`), `views.py` (`api_ai_config`/`api_ai_config_save`, `api_context`/`api_context_save`), `dashboard.html` (AI Context tab). No dedicated migration (fields pre-existed; slack fields added in `0027`).
