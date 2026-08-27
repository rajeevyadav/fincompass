# Private pretrained model bundle

FinCompass may carry owner-local pretrained forecast artifacts whose manifests declare a sharing status.

- `PUBLIC`: eligible for the public-source packaging path after all other release controls pass.
- `RESTRICTED`: private/local use only.
- `REVIEW_REQUIRED`: private/local use is permitted for this handover, but public redistribution is blocked until the upstream data/model-rights review is completed.

The current 12-month bundled reference model is a `validated_research` artifact trained on a real historical monthly sample. It passed the configured statistical gates but does **not** qualify as `validated_market` because the training sample does not establish survivorship/delisting/corporate-action controls to that higher standard.

The public-source manifest generator automatically excludes the model artifact, its manifest, locked-test evidence and summary while its sharing status is `REVIEW_REQUIRED`. `tools/package_private_handover.py` is the explicit owner-local packaging path that includes those files and writes a separate private-model SHA-256 manifest.

No model is pre-activated. The user must explicitly select and activate an eligible model before Live uses it.
