#!/usr/bin/env python3
"""
KassaFu Reader Status Test - Check if Solo terminal is online

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
import requests
from dotenv import load_dotenv

def test_reader_status():
    """Check if Solo terminal is present and online"""
    print("🔍 KassaFu Reader Status Test")
    
    # Check if KassaFu is running
    try:
        health = requests.get('http://localhost:8888/health', timeout=2)
        if health.status_code != 200:
            print("❌ KassaFu server not responding properly")
            print("   Start it with: python3 kassafu.py --server")
            return False
        health_data = health.json()
        print(f"✅ KassaFu server running (mode: {health_data.get('mode', 'unknown')})")
    except requests.exceptions.ConnectionError:
        print("❌ KassaFu server is not running")
        print("   In a separate terminal, run: python3 kassafu.py --server")
        return False
    
    # Check reader status
    print("\n⏳ Checking reader status...")
    
    try:
        response = requests.get('http://localhost:8888/reader/status', timeout=5)
        
        if response.status_code == 200:
            status = response.json()
            
            # Display reader information
            print("\n📡 READER STATUS:")
            print(f"   Online: {'✅ Yes' if status.get('online') else '❌ No'}")
            print(f"   Ready:  {'✅ Yes' if status.get('ready') else '❌ No'}")
            
            if status.get('battery') is not None:
                print(f"   Battery: {status.get('battery')}%")
            if status.get('connection'):
                print(f"   Connection: {status.get('connection')}")
            if status.get('firmware'):
                print(f"   Firmware: {status.get('firmware')}")
            if status.get('state'):
                print(f"   State: {status.get('state')}")
            if status.get('last_activity'):
                print(f"   Last activity: {status.get('last_activity')}")
            
            if status.get('error'):
                print(f"   Error: {status.get('error')}")
            
            # Final verdict
            print("\n" + "="*40)
            if status.get('online') and status.get('ready'):
                print("✅ READER IS ONLINE AND READY FOR PAYMENTS")
                return True
            elif status.get('online'):
                print("⚠️  READER IS ONLINE BUT NOT IDLE")
                print(f"   Current state: {status.get('state')}")
                return False
            else:
                print("❌ READER IS OFFLINE")
                print("   Please check:")
                print("   1. Is the Solo terminal powered on?")
                print("   2. Does it have internet connection (Wi-Fi/Cellular)?")
                print("   3. Is it properly paired with your SumUp account?")
                return False
                
        elif response.status_code == 503:
            print("❌ Terminal not configured or not ready")
            return False
        else:
            print(f"❌ Unexpected response: {response.status_code}")
            print(f"   {response.text}")
            return False
            
    except requests.exceptions.Timeout:
        print("❌ Status check timed out")
        return False
    except Exception as e:
        print(f"❌ Status check failed: {e}")
        return False

def test_payment_exists():
    """Check if the full payment test script exists"""
    import os
    if os.path.exists('./test_payment.py'):
        print("\n💡 For a real payment test (€0.10), run: python3 test_payment.py")
    else:
        print("\n💡 For a real payment test, create test_payment.py")

if __name__ == "__main__":
    load_dotenv()
    
    # Run reader status test
    success = test_reader_status()
    
    if success:
        test_payment_exists()
    
    sys.exit(0 if success else 1)

