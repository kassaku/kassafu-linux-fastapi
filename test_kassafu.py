#!/usr/bin/env python3
"""
KassaFu Test Script - 10 cent sandbox payment
This must be run in SANDBOX mode only
"""

import os
import sys
import time
import json
import requests
from datetime import datetime

def test_payment():
    """Test 10 cent sandbox payment"""
    print("🧪 KassaFu Test: 10 cent sandbox payment")
    
    # Verify we're in sandbox mode
    mode = os.getenv('SUMUP_MODE', 'sandbox')
    if mode != 'sandbox':
        print("❌ Test failed: Must be in SANDBOX mode")
        print("   Set SUMUP_MODE=sandbox in .env file")
        return False
    
    # Check if API key is set
    api_key = os.getenv('SUMUP_API_KEY', '')
    if not api_key:
        print("❌ Test failed: SUMUP_API_KEY not set in .env")
        print("   Get your sandbox API key from SumUp dashboard")
        return False
    
    # Create test order
    test_order_id = f"TEST_{int(time.time())}"
    amount_cents = 10  # 10 cents = €0.10
    
    print(f"\n📝 Test order: {test_order_id}")
    print(f"💰 Amount: €0.10 (10 cents)")
    print(f"🔧 Mode: SANDBOX (Virtual Solo: https://virtual-solo.sumup.com)")
    
    # Make payment request
    print("\n⏳ Sending payment request...")
    
    try:
        response = requests.post(
            'http://localhost:8888/pay',
            json={
                'order_id': test_order_id,
                'amount_cents': amount_cents,
                'currency': 'EUR',
                'items': [
                    {'name': 'Test Item', 'quantity': 1, 'price': amount_cents}
                ],
                'print_receipt': True
            },
            timeout=65
        )
        
        if response.status_code == 200:
            result = response.json()
            
            if result.get('success'):
                print(f"\n✅ Payment successful!")
                print(f"   Transaction ID: {result.get('transaction_id')}")
                print(f"   Status: {result.get('status')}")
                print("\n✅ Test passed")
                return True
            else:
                print(f"\n❌ Payment failed: {result.get('message')}")
                return False
        else:
            print(f"\n❌ HTTP error: {response.status_code}")
            print(f"   Response: {response.text}")
            return False
            
    except requests.exceptions.ConnectionError:
        print("\n❌ Test failed: Cannot connect to KassaFu server")
        print("   Make sure KassaFu is running: python kassafu.py --server")
        return False
    except requests.exceptions.Timeout:
        print("\n❌ Test failed: Payment timeout after 60 seconds")
        print("   Please complete payment on Virtual Solo terminal")
        return False
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        return False

if __name__ == "__main__":
    # Check if KassaFu is running
    try:
        health = requests.get('http://localhost:8888/health', timeout=2)
        if health.status_code != 200:
            print("⚠️  KassaFu server not responding properly")
            print("   Start it with: python kassafu.py --server")
            sys.exit(1)
    except:
        print("⚠️  KassaFu server is not running")
        print("   In a separate terminal, run: python kassafu.py --server")
        sys.exit(1)
    
    # Run test
    success = test_payment()
    sys.exit(0 if success else 1)

