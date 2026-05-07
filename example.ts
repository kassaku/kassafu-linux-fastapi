// Angular service
const response = await fetch('http://localhost:8888/pay', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    order_id: '#2600000001',
    amount_cents: 1500,
    currency: 'EUR',
    items: [
      {name: 'Pizza Margherita', quantity: 2, price: 1250},
      {name: 'Coke', quantity: 1, price: 250}
    ],
    print_receipt: true
  })
});

