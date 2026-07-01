# Worker Report — SOT-1428 (お気に入り機能追加)

## Fallback Disclosure (Worker Non-Response Policy)
- Antigravity CLI was NON-RESPONSIVE: `scripts/ai/run_antigravity.sh` exited 75
  ("authentication failed or timed out" → crash exit 1 → WORKER_NONRESPONSE).
- Codex CLI was also NON-RESPONSIVE for the task check: usage-limit cooldown, exit 75.
- Per the Worker Non-Response Fallback Policy, Claude Code performed BOTH the task check and the
  implementation directly. All Quality Gates apply unchanged.

## Summary
Added a "favorite" (お気に入り) feature to info items.
- New backend boolean field `is_favorite` threaded through both backends (SQLite + Firestore),
  mirroring the existing `needs_deadline_investigation` (SOT-1407) pattern. Reused the existing
  `PUT /info/{id}` (`updateInfo`) endpoint — no new endpoint.
- To-do list (やることリスト = TasksPage via `DatedInfoList`): each row gets a star TOGGLE button.
  Filled yellow star when favorited; outline star when not. Clicking toggles `is_favorite` without
  navigating (preventDefault + stopPropagation).
- Board (掲示板 = DashboardPage): a filled yellow star is shown ONLY for favorited items
  (display-only, all four sections: today / tomorrow / weekly / nextWeek).

## Changed Files
- `backend/app/models.py` — add `is_favorite` Boolean column (nullable, default False).
- `backend/app/schemas.py` — add `is_favorite` to `NurseryInfoBase` (default False) and
  `NurseryInfoUpdate` (default None).
- `backend/app/repository.py` — add `is_favorite` to `FirestoreNurseryInfo` dataclass and to
  `_info_doc_to_obj` mapping. (create/update use model_dump → generic.)
- `frontend/src/types/index.ts` — add `is_favorite?: boolean` to `NurseryInfo` and `NurseryInfoCreate`.
- `frontend/src/i18n/messages.ts` — add `favorite.add` / `favorite.remove` (ja + en).
- `frontend/src/components/FavoriteStar.tsx` — NEW shared inline-SVG star (filled/outline).
- `frontend/src/components/DatedInfoList.tsx` — favorite toggle button (gated to namespace='tasks'),
  useMutation(updateInfo) + query invalidation.
- `frontend/src/pages/DashboardPage.tsx` — display-only favorite star in all 4 board sections.

## Commands Run
- (quality gate run by Claude Code — see Codex report / final report)

## Acceptance Criteria
- [x] favorite toggle star on to-do list, filled yellow when active
- [x] favorite indicator star shown only for favorited items on to-do list (toggle is the indicator)
- [x] favorite indicator star shown only for favorited items on board
- [x] is_favorite persisted via PUT /info/{id} (SQLite + Firestore)

## Risks
- No icon library; used inline SVG (consistent with repo).
- DatedInfoList is shared with SchedulePage; toggle is gated to namespace='tasks' so the schedule
  list is unchanged.
- Existing rows have NULL is_favorite → treated as not favorited (backward compatible).

## Next Action
READY_FOR_REVIEW
