# kassafu
Payments for payment terminals like SumUp, interface to Angular website as a backend.
KassaFu — The payment bridge between SumUp terminals and your restaurant system.

So KassaFu means:
    Kassa (Dutch) = cash register
    Fu (付款) = payment

# Requirements

## R1	Accept payment requests from the main server via Angular.	🔴 High
The interface between Angular and this Python script is running on the same PC.
## R2	Communicate with SumUp Cloud API to start Solo terminal payments. 	🔴 High
## R3	Wait for payment completion and report status back.	🔴 High
## R4	Trigger receipt printing on the Solo's built-in printer. 	🟡 Medium
## R5	Handle webhooks for asynchronous payment confirmation. 	🟡 Medium
## R6	Support sandbox mode for testing without real money. 	🔴 High
## R7	Log all transactions for audit purposes.	🟡 Medium
## R8 Small test script in Python to do a payment of 10 cent in a sandbox. 🔴 Highest
## R9 Re-use for other applications like C++ or terminal.	🟡 Medium
