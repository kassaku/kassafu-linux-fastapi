#!/usr/bin/env python3
"""
KassaFu Test Script - 10 cent real payment
This must be run in REAL mode only

Copyright (c) 2026 Houkes Horeca Applications

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import os
import sys
import time
import json
import requests
from datetime import datetime
from typing import Optional, Dict, Tuple
from dotenv import load_dotenv

# Constants
KASSAFU_URL = "http://localhost:8888"
POLL_INTERVAL = 2  # seconds
MAX_POLL_ATTEMPTS = 30  # 30 * 2 = 60 seconds max wait


def check_server_health() -> Tuple[bool, str]:
    """Check if KassaFu server is running and healthy."""
    try:
        response = requests.get(f'{KASSAFU_URL}/health', timeout=2)
        if response.status_code == 200:
            health_data = response.json()
            mode = health_data.get('mode', 'unknown')
            terminal_ready = health_data.get('terminal_ready', False)
            if terminal_ready:
                return True, f"Server running (mode: {mode})"
            else:
                return True, f"Server running but terminal not ready (mode: {mode})"
        else:
            return False, f"Server responded with HTTP {response.status_code}"
    except requests.exceptions.ConnectionError:
        return False, "Server not running"
    except requests.exceptions.Timeout:
        return False, "Server timeout"
    except Exception as e:
        return False, f"Error: {e}"


def check_reader_status() -> Tuple[bool, str, Optional[Dict]]:
    """Check if the Solo terminal is online and ready."""
    try:
        response = requests.get(f'{KASSAFU_URL}/reader/status', timeout=5)
        
        if response.status_code == 200:
            status = response.json()
            
            if status.get('error'):
                error_msg = status.get('error')
                if '401' in error_msg:
                    return False, "API key invalid or unauthorized", status
                elif '404' in error_msg:
                    return False, "Reader not found", status
                else:
                    return False, f"Reader error: {error_msg}", status
            
            if status.get('online') and status.get('ready'):
                return True, "Reader is online and ready", status
            elif status.get('online'):
                return False, f"Reader online but not idle (state: {status.get('state')})", status
            else:
                return False, "Reader is offline", status
        elif response.status_code == 503:
            return False, "Terminal not configured", None
        else:
            return False, f"HTTP {response.status_code}", None
            
    except requests.exceptions.Timeout:
        return False, "Status check timeout", None
    except Exception as e:
        return False, f"Status check failed: {e}", None


def initiate_payment(order_id: str, amount_cents: int) -> Tuple[bool, str, Optional[Dict]]:
    """Initiate a payment request to KassaFu."""
    try:
        response = requests.post(
            f'{KASSAFU_URL}/pay',
            json={
                'order_id': order_id,
                'amount_cents': amount_cents,
                'currency': 'EUR'
            },
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            
            if result.get('success'):
                return True, "Payment initiated", result
            else:
                return False, result.get('message', 'Unknown error'), result
        else:
            return False, f"HTTP {response.status_code}: {response.text}", None
            
    except requests.exceptions.ConnectionError:
        return False, "Cannot connect to KassaFu server", None
    except requests.exceptions.Timeout:
        return False, "Request timeout", None
    except Exception as e:
        return False, f"Error: {e}", None


def poll_payment_status(order_id: str, max_attempts: int = MAX_POLL_ATTEMPTS) -> Tuple[bool, str, Optional[Dict]]:
    """
    Poll payment status until completion, failure, or timeout.
    
    Returns:
        Tuple of (success, message, status_data)
    """
    print(f"\n⏳ Waiting for payment (max {max_attempts * POLL_INTERVAL} seconds)...")
    
    for attempt in range(max_attempts):
        try:
            response = requests.get(
                f'{KASSAFU_URL}/payment/status',
                params={'order_id': order_id},
                timeout=5
            )
            
            if response.status_code == 200:
                status_data = response.json()
                payment_status = status_data.get('status')
                
                if payment_status == 'paid':
                    amount = status_data.get('amount', 0)
                    return True, f"Payment complete (€{amount})", status_data
                elif payment_status == 'failed':
                    # Get the reason from the response
                    reason = status_data.get('message', 'Payment failed')
                    return False, reason, status_data
                elif payment_status == 'pending':
                    # Still waiting, show progress every few attempts
                    if attempt > 0 and attempt % 5 == 0:
                        print(f"   Still waiting... ({attempt * POLL_INTERVAL}s)", end='\r')
                    time.sleep(POLL_INTERVAL)
                    continue
                else:
                    return False, f"Unknown status: {payment_status}", status_data
            else:
                return False, f"Status check failed: HTTP {response.status_code}", None
                
        except requests.exceptions.Timeout:
            print(f"\n   Timeout on attempt {attempt + 1}, retrying...")
            time.sleep(POLL_INTERVAL)
            continue
        except Exception as e:
            return False, f"Status check error: {e}", None
    
    return False, f"Timeout after {max_attempts * POLL_INTERVAL} seconds", None


def test_payment():
    """Test 108 cent real payment with full flow"""
    print("=" * 50)
    print("🧪 KassaFu Test: 108 cent real payment")
    print("=" * 50)
    
    # Step 1: Check if KassaFu server is running
    print("\n📡 Step 1: Checking KassaFu server...")
    server_ok, server_msg = check_server_health()
    if not server_ok:
        print(f"   ❌ {server_msg}")
        print("   Start it with: python3 kassafu.py --server")
        return False
    print(f"   ✅ {server_msg}")
    
    # Step 2: Check reader status
    print("\n📡 Step 2: Checking reader status...")
    reader_ok, reader_msg, reader_status = check_reader_status()
    if not reader_ok:
        print(f"   ❌ {reader_msg}")
        if reader_status and reader_status.get('error'):
            if '401' in reader_status.get('error', ''):
                print("   → API key is invalid. Check config.json")
            elif '404' in reader_status.get('error', ''):
                print("   → Reader not found. Check reader_id in config.json")
        print("\n❌ Test failed: Terminal offline")
        return False
    print(f"   ✅ {reader_msg}")
    
    # Show battery/connection info if available
    if reader_status:
        if reader_status.get('battery') is not None:
            print(f"   🔋 Battery: {reader_status.get('battery')}%")
        if reader_status.get('connection'):
            print(f"   📶 Connection: {reader_status.get('connection')}")
    
    # Step 3: Create test order
    test_order_id = f"TEST_{int(time.time())}"
    amount_cents = 108  # 108 cents = €1.08
    
    print(f"\n📝 Step 3: Creating test order")
    print(f"   Order ID: {test_order_id}")
    print(f"   Amount: €{amount_cents/100} ({amount_cents} cents)")
    print(f"   Mode: REAL")
    
    # Step 4: Initiate payment
    print("\n💳 Step 4: Initiating payment...")
    print("   Please tap your card on the Solo terminal")
    
    init_success, init_msg, init_data = initiate_payment(test_order_id, amount_cents)
    if not init_success:
        print(f"   ❌ {init_msg}")
        return False
    print(f"   ✅ {init_msg}")
    
    # Step 5: Wait for payment completion
    print("\n⏳ Step 5: Waiting for payment...")
    success, final_message, status_data = poll_payment_status(test_order_id)
    
    # Step 6: Final result
    print("\n" + "=" * 50)
    if success:
        print(f"✅ TEST PASSED - {final_message}")
    else:
        print(f"❌ TEST FAILED - {final_message}")
    print("=" * 50)
    
    return success


def main():
    """Main entry point"""
    load_dotenv()
    
    # Quick server check before starting
    try:
        health = requests.get(f'{KASSAFU_URL}/health', timeout=2)
        if health.status_code != 200:
            print("⚠️  KassaFu server not responding properly")
            print("   Start it with: python3 kassafu.py --server")
            sys.exit(1)
    except:
        print("⚠️  KassaFu server is not running")
        print("   In a separate terminal, run: python3 kassafu.py --server")
        sys.exit(1)
    
    # Run test
    success = test_payment()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
