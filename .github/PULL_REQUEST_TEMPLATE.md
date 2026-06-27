## Summary

Describe the change.

## Validation

- [ ] `ruff check src/opentalking/core src/opentalking/server src/opentalking/worker src/opentalking/llm src/opentalking/tts src/opentalking/avatars src/opentalking/events src/opentalking/rtc apps/api apps/unified apps/cli tests`
- [ ] `mypy src/opentalking/core src/opentalking/server src/opentalking/worker src/opentalking/llm src/opentalking/tts src/opentalking/avatars src/opentalking/events src/opentalking/rtc apps/api apps/unified apps/cli --ignore-missing-imports`
- [ ] `pytest apps/api/tests apps/worker/tests tests`
- [ ] `cd apps/web && npm run build`

## Notes

List migration impact, operational changes, or follow-up items.
