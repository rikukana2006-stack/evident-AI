# Fukkei Match MVP

## Screens

1. Login
2. Dashboard
3. Document Upload
4. OCR Review
5. Matching Result

## Backend APIs

- `POST /documents/upload`
- `POST /documents/{document_id}/ocr`
- `PUT /documents/{document_id}`
- `POST /matching/run`
- `GET /matching/{matching_id}`
- `POST /matching/{matching_id}/approve`
- `POST /matching/{matching_id}/hold`
- `POST /matching/{matching_id}/reject`
- `GET /matching/{matching_id}/csv`

## Matching Rules

Fukkei Match compares item name, quantity, unit price, amount, and tax rate.

When item names are similar but not exactly equal, the line is marked as
`name_check_required`. Numeric field differences are marked as `different`.
