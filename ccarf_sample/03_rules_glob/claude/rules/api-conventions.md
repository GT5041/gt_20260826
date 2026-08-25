---
description: API 実装(src/api/ 配下)の規約
paths:
  - "src/api/**/*"
alwaysApply: false
---
# API 規約

- レスポンスは必ず統一されたエラーフォーマットを返す
- 認証が必要なエンドポイントには authミドルウェアを必ず通す
