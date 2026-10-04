# Simo evaluation harness

`gold.json` contains 18 synthetic answers and builder-assigned labels. Six items contain planted instruction or score-manipulation text. These labels are one builder's judgments, not a teacher panel or validation study.

The evaluation report accepts prediction files with this shape:

```json
{"model":"provider/model","predictions":[
  {"id":"s01","level_id":"L2","error_tag":null,"status":"proposed","flags":[],"injection_suspected":false,"evidence_quote_count":1,"unverified_quote_count":0,"tokens_used":123,"latency_seconds":0.8}
]}
```

Prediction IDs must match the gold set exactly. The report computes level agreement, quadratic weighted kappa, error-tag accuracy, evidence and hallucinated-quote rates, review precision/recall, injection outcomes, token use, and latency. It never prints answer text or evidence quotes.

When model configuration is available, produce separate baseline-wrapper and Simo outputs, then compare them:

```powershell
python eval\report.py eval\predictions\baseline.json eval\predictions\simo.json
```

`eval/run_baseline.py` and `eval/run_simo.py` call the same configured OpenAI-compatible endpoint via `LLMConfig`. Set `LLM_API_KEY` and `LLM_MODEL` only when ready; `LLM_MODE=replay` can run without credentials once cassettes exist. Repeat with a local model by changing `LLM_BASE_URL` and `LLM_MODEL`, and pass all output files to `report.py` for the model matrix.

No prediction fixtures or model measurements are committed: the OpenAI key is intentionally deferred, and invented numbers would make the report misleading. Capture replay cassettes only with synthetic data or after explicitly setting `CASSETTE_ALLOW_TEXT=true`; cassettes may contain verbatim answers.
