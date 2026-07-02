# 0004. 永続化に Firestore と SQLite を併用する

- Status: Accepted
- Date: 2026-07-02
- Related: SOT-1470（バックフィル）, `docs/persistence-architecture.md`

## Context（背景）

お知らせデータ・子ども情報・添付などの永続化方式を決める必要があった。ローカル開発／
テストの手軽さと、本番（Cloud Run）でのマネージド永続化の両立が求められた。詳細な
設計は `docs/persistence-architecture.md` にある。

## Decision（決定）

永続化は **Firestore と SQLite を併用** する。用途に応じて使い分け、ローカル／テストでは
SQLite、本番ではマネージドな Firestore を利用する構成とする（詳細は
`docs/persistence-architecture.md` を参照）。

## Alternatives（検討した代替案）

- 単一 RDB（Cloud SQL 等）のみ — 常時起動インスタンスの固定費が発生し、
  サーバレス（Cloud Run）＋従量課金の方針に合わない。
- Firestore のみ（ローカルもエミュレータ）— ローカル開発・単体テストの手軽さが下がる。

## Consequences（結果）

- ローカル／テストは SQLite で高速・簡便、本番は Firestore でスケール・運用委譲。
- 2 系統のデータアクセスを保つコストがあるため、リポジトリ層で抽象化する。
- 詳細・整合性の考慮は `docs/persistence-architecture.md` を一次情報とする。
