#!/usr/bin/env python3
"""
Debug script for cTrader connection
Tests connection step by step with detailed logging
"""

import asyncio
import sys
import os
from ctrader_bot import SimpleCTraderBot
import time


async def debug_connection():
    """Debug the cTrader connection step by step"""
    
    print("="*60)
    print("  cTrader Connection Debug")
    print("="*60)
    print()
    
    # Check .env file
    if not os.path.exists('.env'):
        print("✗ ERROR: .env file not found!")
        return False
    
    print("✓ .env file found")
    
    # Initialize bot
    print("\nCreating bot instance...")
    try:
        bot = SimpleCTraderBot()
        print("✓ Bot instance created")
    except Exception as e:
        print(f"✗ Failed to create bot: {e}")
        return False
    
    # Start connection in a separate thread
    import threading
    from twisted.internet import reactor
    
    def run_reactor():
        reactor.run(installSignalHandlers=False)
    
    print("\nStarting Twisted reactor...")
    reactor_thread = threading.Thread(target=run_reactor, daemon=True)
    reactor_thread.start()
    
    print("Starting bot connection...")
    bot.start()
    
    # Monitor connection progress with detailed status
    print("\nMonitoring connection progress...")
    max_wait = 120  # 2 minutes timeout for debugging
    
    for i in range(max_wait):
        await asyncio.sleep(1)
        
        # Print status every 5 seconds
        if i % 5 == 0:
            print(f"\n--- Status after {i} seconds ---")
            print(f"Connected: {bot.is_connected}")
            print(f"App authenticated: {bot.is_app_authenticated}")
            print(f"Account authenticated: {bot.is_account_authenticated}")
            print(f"Symbols loaded: {len(bot.symbols)}")
            
        # Check if fully ready
        if bot.is_account_authenticated and len(bot.symbols) > 0:
            print(f"\n✓ SUCCESS! Connection established after {i} seconds")
            print(f"✓ Symbols loaded: {len(bot.symbols)}")
            
            # Show first few symbols
            symbol_names = list(bot.symbols.keys())[:5]
            print(f"✓ Sample symbols: {symbol_names}")
            
            return True
    
    print(f"\n✗ TIMEOUT after {max_wait} seconds")
    print(f"Final status:")
    print(f"  Connected: {bot.is_connected}")
    print(f"  App authenticated: {bot.is_app_authenticated}")
    print(f"  Account authenticated: {bot.is_account_authenticated}")
    print(f"  Symbols loaded: {len(bot.symbols)}")
    
    return False


if __name__ == "__main__":
    result = asyncio.run(debug_connection())
    sys.exit(0 if result else 1)