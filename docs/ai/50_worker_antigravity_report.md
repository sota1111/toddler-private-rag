# Worker Report — SOT-1450 (使い方の動画生成プロンプト)

## Summary
Antigravity CLI was NON-RESPONSIVE: `scripts/ai/run_antigravity.sh` exited `75`
(`WORKER_NONRESPONSE: antigravity (crash (exit 1)) — authentication failed or timed out`).
Per the Worker Non-Response Fallback Policy, Claude Code performed this DOC implementation directly.

Created `docs/howto-video-prompt.md`: a Japanese prompt to give to a general video-generation AI
(Runway / Pika / Sora / Veo) to produce a how-to slideshow video. The video uses the existing
`frontend/public/howto/*.png` app screenshots (screens only — no live-action/people), with subtitles
that reuse the app's real `howto.*` copy so there is no drift from the app.

## Fallback Disclosure (audit)
- Non-responsive worker: Antigravity CLI
- Detected failure mode: exit code 75 (auth failure / non-response marker)
- Retry: not retried — persistent auth failure across recent runs; fell back immediately per policy
- Work performed by: Claude Code (fallback)

## Changed Files
- `docs/howto-video-prompt.md` — NEW. Video-generation prompt: overall direction (9:16 slideshow,
  screenshots only, Ken Burns + crossfade, 60–90s), 8-scene storyboard (opening + 7 how-to screens +
  closing) with per-scene image path / title subtitle / body subtitle / duration, subtitles copied
  from the `howto.*` Japanese strings, and an English-swap note pointing to the `howto.*` English strings.

## Commands Run
- `ls -1 frontend/public/howto/*.png` — confirmed all 7 referenced captures exist.
- `grep -n "howto" frontend/src/i18n/messages.ts` — confirmed ja + en `howto.*` title/body keys exist and match the subtitles used.

## Acceptance Criteria
- [x] `docs/howto-video-prompt.md` created
- [x] Includes overall direction + scene storyboard + subtitles (real howto copy) + duration/transition guidance
- [x] References all 7 existing captures by correct path in the correct (HowToPage) order
- [x] No app code / image / i18n changes (doc-only)

## Risks
- Doc-only change; no lint/typecheck/test impact. The prompt references screenshots by repo path — the
  end user attaches those PNGs to the video AI as "提供画像1〜7".

## Next Action
READY_FOR_REVIEW
