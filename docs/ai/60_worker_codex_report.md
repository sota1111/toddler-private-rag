# Worker Report

## Summary
Task check for SOT-1284 「データが見つかりませんでした」.

**Worker non-response (audit):** Codex CLI was non-responsive — `scripts/ai/run_codex.sh`
exited with the dedicated non-response code `75` (usage-limit cooldown active). Per the Worker
Non-Response Fallback Policy, Claude Code performed this task check directly.

**Actionable:** Yes. Clear, reproducible FIX-type bug with a single root cause.

**Root cause:** After the Firestore migration (SOT-1278), record ids are **strings**, but the
frontend still treats the detail-page id as a `number`.
- List pages link with the raw string id: `/data/${item.id}` (DataListPage / DashboardPage),
  so the URL carries the correct Firestore string id and the list renders fine.
- The detail page parses it as a number: `frontend/src/pages/DataDetailPage.tsx:347`
  `const id = Number(params.id)` → `NaN` for a Firestore string id.
- The detail query is then gated by `enabled: Number.isFinite(id)`
  (`DataDetailPage.tsx:31`), which is `false` for `NaN`, so `getInfoById` never runs and the
  page renders `records.notFound` = 「データが見つかりませんでした」.

This is the frontend counterpart of the SOT-1282 backend fix (`id: int` → `Union[int, str]`);
the backend already accepts string ids, but the frontend still coerces to number.

## Changed Files
- none (task check only)

## Commands Run
- `grep -n "Number(params|enabled|getInfoById" frontend/src/pages/DataDetailPage.tsx`
- `grep -rn "Number(params.id|parseInt(params" frontend/src` → only hit: DataDetailPage.tsx:347
- `grep -n "id" frontend/src/types/index.ts` (NurseryInfo.id / Attachment.id / info_id still `number`)
- `grep -n "getInfoById|updateInfo|deleteInfo|getAttachmentFileUrl" frontend/src/api/index.ts`

## Acceptance Criteria
- [x] Root cause of detail "データが見つかりませんでした" identified
- [x] Minimal fix location named: `frontend/src/pages/DataDetailPage.tsx` (id parsing + query enable),
      with supporting type widening in `frontend/src/types/index.ts` and `frontend/src/api/index.ts`.

## Risks
- Must keep `key={id}` remount behavior (string key is fine).
- Widen id types to `number | string` (not replace with `string`) to stay backward compatible with
  sqlite int ids and existing numeric callers.
- Attachment ids are also Firestore strings; widen `Attachment.id`/`info_id` and attachment api
  id params too so `getAttachmentFileUrl`/`deleteAttachment` type-check with string ids.

## Next Action
READY_FOR_REVIEW
