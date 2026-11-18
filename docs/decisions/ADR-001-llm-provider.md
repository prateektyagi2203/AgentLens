# ADR-001: LLM provider is pluggable, OpenAI is the default
Date: 2026-11-18
Status: Accepted
## Context
The PRD names the Claude API for the optional LLM layer. The builder holds an OpenAI API key; Claude Pro and Gemini Pro are chat subscriptions without API access.
## Decision
All LLM use goes through one `LLMProvider` interface (`mock`, `openai`). `AGENTLENS_LLM_PROVIDER` selects it; the default is `mock`, so the product runs with no key. Anthropic or Gemini providers can be added behind the same interface.
## Alternatives considered
Hard-wiring Claude (no usable key); supporting three providers now (unused code, untestable).
## Consequences
Rules-only mode stays the baseline. LLM output is always schema-validated and cached by prompt hash.
