#!/usr/bin/env  sh

# Test payment
curl -X POST http://localhost:8888/pay \
  -H "Content-Type: application/json" \
  -d '{
    "order_id": "TEST-001",
    "amount_cents": 100,
    "currency": "EUR",
    "items": [{"name": "Coffee", "quantity": 1, "price": 100}],
    "print_receipt": true
  }'

