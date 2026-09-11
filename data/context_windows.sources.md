# Context Window Table — Sources & Maintenance

**Verified:** 2026-09-11 · **Entries:** 249 · **Table file:** [`context_windows.json`](./context_windows.json)

This table powers GamesAI's automatic context management: the plugin matches your `ai_model`
to a window size and compresses the conversation once the context reaches 80 % of that window
(or a single request reaches 20 %). Any AI entry can override the table with its own
`context_window` value — recommended for local deployments and for cost control.

## Maintenance

```bash
# 1) Edit data/context_windows.json directly
#    (or create .tmp_part_*.json research batches and merge them)
python tools/build_context_table.py --merge    # merge research batches into the repo table
python tools/build_context_table.py            # rebuild the bundled table from the repo table + verify
python tools/build_context_table.py --check     # verify only, write nothing
```

The script embeds `data/context_windows.json` verbatim into `games_ai/context_table.py`
(the offline fallback), so the two can never drift apart.

Matching rules: **exact id → longest wildcard → `*`**. Vendor-prefixed ids
(`openai/gpt-4o`, `x-ai/grok-4`, …) are matched after stripping the prefix.

## Official sources per provider

| Provider | Official sources | Notes |
|---|---|---|
| DeepSeek | [Models & pricing](https://api-docs.deepseek.com/quick_start/pricing) · [Changelog](https://api-docs.deepseek.com/updates) · [Chat API](https://api-docs.deepseek.com/api/create-chat-completion) | Since 2026-09-10 the current id is `deepseek-flash` (V4.1-Flash); `deepseek-v4-flash` / `-vision-exp` are offline but temporarily routed; `deepseek-v4-pro` keeps being served |
| Kimi / Moonshot | [Models](https://platform.kimi.com/docs/models) · [Pricing](https://platform.kimi.com/docs/pricing/chat) · kimi-k3 / k2.7 / k2.6 quickstarts | `moonshot-v1-*`, `kimi-k2*` and `kimi-k2.5` are discontinued by the vendor; legacy values are kept for third-party gateways |
| Zhipu GLM | [Model overview](https://docs.bigmodel.cn/cn/guide/start/model-overview) · individual model pages | Flagship GLM-5.3 = 1M/128K; GLM-4.5 is being retired; `glm-4-airx` is only 8K |
| OpenAI | [Microsoft Foundry official model documentation](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure) (OpenAI's own doc site returns 403 to this toolchain, so the official mirrored specs plus verbatim model-card quotes from OpenAI's developer community were used) | GPT-6 Astra 1,050,000/128,000; GPT-5.x 400K–1.05M; o-series 200K/100K; GPT-4.1 1,047,576/32,768; GPT-4o 128K/16,384 |
| xAI Grok | [docs.x.ai model pages](https://docs.x.ai/developers/models/grok-4.6) (fetched with a browser user agent) · [x.ai/news](https://x.ai/news/grok-4) | Grok 4.6/4.5 = 500K; 4.3/4.20 = 1M; build-0.1 = 256K; **no hard output limit is published** — 128K is the API default |
| Anthropic Claude | [Models overview](https://platform.claude.com/docs/en/models/overview) · [Deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations) | 5.x and 4.6+ = 1M/128K (1M is the **default**, no beta header); 4.5 family = 200K/64K; the whole Claude 3 family is retired |
| Google Gemini | [Models](https://ai.google.dev/gemini-api/docs/models) · [Deprecations](https://ai.google.dev/gemini-api/docs/deprecations) | Gemini 3.x = 1,048,576/65,536; 2.0-flash shut down 2026-06-01; 2.5-pro retires 2026-10-20 on Vertex AI |
| Alibaba Qwen (Bailian) | [Model list](https://help.aliyun.com/zh/model-studio/model-list-text-generation) · individual model pages | **API model ids use a dot** (`qwen3.8-max`) while doc slugs use dashes; `qwen-long`'s 10M window is file-upload only — HTTP requests are limited to 1M |
| ByteDance Doubao (Volcengine Ark) | [Model list](https://docs.volcengine.com/docs/82379/1330310) | `doubao-seed-evolving` = 1M; seed-2-0 family has a **256K window but only 224K max input**; the seed-1-6 batch reaches EOS on 2026-09-21 |
| Baidu ERNIE (Qianfan) | [Model documentation](https://cloud.baidu.com/doc/qianfan/s/rmh4stp0j) | the bare id `ernie-4.5-turbo` is not valid — only `-32k` / `-128k` / dated snapshots exist |
| Tencent Hunyuan | [TokenHub models](https://cloud.tencent.com/document/product/1823/130051) · [Retirement notice](https://cloud.tencent.com/document/product/1729/131925) | migrated to TokenHub; 46 legacy ids were retired on 2026-06-22, the official migration target is `hy3` |
| MiniMax | [OpenAI-compatible API docs](https://platform.minimax.io/docs/api-reference/text-chat-openai) | **context = input + output**; M3 = 1M; M2.x = 204,800 with `max_tokens` capped at the whole window; `M2-her` has no `MiniMax-` prefix |
| StepFun | [Step 3.7 Flash](https://platform.stepfun.com/docs/zh/guides/models/step-3.7-flash) | 256K; `step-2-*` / `step-3` were retired on 2026-07-08 |
| iFlytek Spark | [HTTP API docs](https://www.xfyun.cn/doc/spark/HTTP%E8%B0%83%E7%94%A8%E6%96%87%E6%A1%A3.html) · [X1/X2 docs](https://www.xfyun.cn/doc/spark/X1http.html) | `spark-x` maps to **three different windows** depending on the endpoint (`/v2/`, `/x2/`, `/agent/v1/`) |
| Meta Llama | [Llama 3.1 model card](https://github.com/meta-llama/llama-models/blob/main/models/llama3_1/MODEL_CARD.md) · [Llama 4 model card](https://github.com/meta-llama/llama-models/blob/main/models/llama4/MODEL_CARD.md) · AWS Bedrock model cards | Llama 3.x = 128K; Llama 4 Scout advertises 10M but **no host actually serves it** |
| Mistral | [Model overview](https://docs.mistral.ai/getting-started/models/models_overview/) + AWS Bedrock model cards | Mistral does not publish output limits; output values come from Bedrock. Ministral 3.x is 256K at Mistral but most hosts cap it at 128K |
| Cohere | [Models](https://docs.cohere.com/docs/models) | Command A / R families; Aya models use the `c4ai-` prefix |
| Groq (hosted) | [Groq models](https://console.groq.com/docs/models) · [Deprecations](https://console.groq.com/docs/deprecations) | hosts open-weight models; windows may differ from the vendor's own API |
| OpenRouter | [Models API](https://openrouter.ai/api/v1/models) | exposes `context_length`; ⚠️ `max_completion_tokens` is often a synthetic 0.8/0.9 × context value and **must not be trusted** |
| Local deployments | see below | the window depends on launch parameters — use the per-AI `context_window` override |

## Local / self-hosted runtimes: how to read the real window

| Runtime | Endpoint | Field |
|---|---|---|
| Ollama | `POST /api/show` (trained max) · `GET /api/ps` (runtime allocation) | `model_info["<arch>.context_length"]` · `models[].context_length` |
| llama.cpp server | `GET /props` (per slot) · `GET /v1/models` (trained max) | `default_generation_settings.n_ctx` · `data[].meta.n_ctx_train` |
| vLLM | `GET /v1/models` | `data[].max_model_len` (enabled by default; this *is* the served limit) |
| LM Studio | `GET /api/v1/models` (native namespace; `/api/v0` is deprecated) | `models[].max_context_length` · `loaded_instances[].config.context_length` |

> Ollama's default `num_ctx` is **not** 4096 (the old FAQ entry is stale): it is resolved
> automatically from VRAM (<24 GiB → 4096, 24–48 GiB → 32768, ≥48 GiB → 262144).
> The 80 % trigger should use the **runtime** field, not the trained maximum.

## Semantics to be aware of

1. **"Context window" ≠ "max input"**: Doubao seed-2-0 (256K window / 224K max input), Tencent
   `hy3` (256K / 192K) and MiniMax (window = input + output) all differ. The 80 % trigger stays
   safe for these models (it reserves 20 % for output); each entry's `note` documents it.
2. **Input, output and reasoning tokens share one budget** (stated by OpenAI, xAI and Azure).
   For reasoning models the reasoning tokens count against the output allowance.
3. **xAI publishes no hard output limit**; the table's 128,000 is the documented API default and
   can be raised per request.
4. **Hosting-platform caps are not model limits**: the same Grok is 200K on Azure, 128K on Oracle
   OCI, and 500K on xAI direct.
5. **Retired models may still be served by third-party gateways** (`moonshot-v1-*`, `claude-3-*`,
   `deepseek-chat`, …), so the table keeps their historical values and marks their status in `note`.
6. **Live-test correction:** the DeepSeek deprecation notice said `deepseek-chat` /
   `deepseek-reasoner` would stop on 2026-07-24, but both still answered successfully on
   2026-09-11, so their V3.2 specs are kept.

## Version history

| Date | Change |
|---|---|
| 2026-08-30 | Initial table: 26 entries (DeepSeek v4, GPT-4o/4.1, Claude 3.x/4, GLM-4, Qwen2.5/3, Gemini 2.5) |
| 2026-09-11 | Full rewrite: **249 entries** across 19 providers and hosting platforms; added the `note` field for semantics and lifecycle status; added this sources document and the build script |
