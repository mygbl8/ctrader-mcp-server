#!/usr/bin/env python3
"""
Simple authentication test without threading complexity
"""

import asyncio
import os
import sys
from twisted.internet import reactor, asyncioreactor
from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *
from ctrader_open_api.messages.OpenApiMessages_pb2 import *
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import *
from dotenv import load_dotenv
import threading
import time

# Load environment variables
load_dotenv()

def test_credentials():
    """Test if credentials are valid"""
    
    print("="*60)
    print("  cTrader Credentials Test")
    print("="*60)
    
    # Load credentials
    client_id = os.getenv('CLIENT_ID')
    client_secret = os.getenv('CLIENT_SECRET')
    access_token = os.getenv('ACCESS_TOKEN')
    account_id = os.getenv('ACCOUNT_ID')
    host_type = os.getenv('HOST', 'demo').lower()
    
    print(f"\nCredentials check:")
    print(f"  CLIENT_ID: {'✓' if client_id else '✗'}")
    print(f"  CLIENT_SECRET: {'✓' if client_secret else '✗'}")
    print(f"  ACCESS_TOKEN: {'✓' if access_token else '✗'}")
    print(f"  ACCOUNT_ID: {'✓' if account_id else '✗'} ({account_id})")
    print(f"  HOST: {host_type}")
    
    if not all([client_id, client_secret, access_token, account_id]):
        print("❌ Missing credentials!")
        return False
    
    # Quick connection test in separate thread to avoid reactor conflicts
    result = {'success': False, 'error': None, 'details': {}}
    
    def test_connection():
        try:
            # Connection state
            state = {
                'connected': False,
                'app_auth': False,
                'account_auth': False,
                'symbols': 0
            }
            
            def on_connected(client):
                state['connected'] = True
                print("  ✓ Connected")
                
                # Send app auth request
                request = ProtoOAApplicationAuthReq()
                request.clientId = client_id
                request.clientSecret = client_secret
                client.send(request)
            
            def on_message(client, message):
                try:
                    # App auth response
                    if message.payloadType == ProtoOAApplicationAuthRes().payloadType:
                        state['app_auth'] = True
                        print("  ✓ Application authenticated")
                        
                        # Send account auth request
                        request = ProtoOAAccountAuthReq()
                        request.ctidTraderAccountId = int(account_id)
                        request.accessToken = access_token
                        client.send(request)
                    
                    # Account auth response
                    elif message.payloadType == ProtoOAAccountAuthRes().payloadType:
                        state['account_auth'] = True
                        print("  ✓ Account authenticated")
                        
                        # Request symbols
                        request = ProtoOASymbolsListReq()
                        request.ctidTraderAccountId = int(account_id)
                        client.send(request)
                    
                    # Symbols response
                    elif message.payloadType == ProtoOASymbolsListRes().payloadType:
                        response = Protobuf.extract(message)
                        state['symbols'] = len(response.symbol)
                        print(f"  ✓ Loaded {state['symbols']} symbols")
                        
                        result['success'] = True
                        result['details'] = state.copy()
                        reactor.stop()
                    
                    # Error response
                    elif message.payloadType == ProtoOAErrorRes().payloadType:
                        error_response = Protobuf.extract(message)
                        print(f"  ❌ API Error: {error_response.description}")
                        result['error'] = f"API Error: {error_response.description}"
                        reactor.stop()
                        
                except Exception as e:
                    print(f"  ❌ Message processing error: {e}")
                    result['error'] = str(e)
                    reactor.stop()
            
            def on_disconnected(client, reason):
                print(f"  ❌ Disconnected: {reason}")
                if not result['success']:
                    result['error'] = f"Disconnected: {reason}"
                reactor.stop()
            
            def timeout():
                print("  ⏰ Timeout reached")
                if not result['success']:
                    result['error'] = "Timeout - check network connectivity"
                reactor.stop()
            
            # Set up client
            host = "demo.ctraderapi.com" if host_type == "demo" else "live.ctraderapi.com"
            client = Client(host, 5035, TcpProtocol)
            client.setConnectedCallback(on_connected)
            client.setDisconnectedCallback(on_disconnected)
            client.setMessageReceivedCallback(on_message)
            
            # Start with timeout
            reactor.callLater(15, timeout)
            client.startService()
            reactor.run()
            
        except Exception as e:
            result['error'] = str(e)
    
    print(f"\n🔗 Testing connection to cTrader API...")
    
    # Run in thread to avoid reactor conflicts
    thread = threading.Thread(target=test_connection)
    thread.start()
    thread.join()
    
    # Show results
    print(f"\n📊 Test Results:")
    if result['success']:
        details = result['details']
        print("  ✅ SUCCESS - All credentials are valid!")
        print(f"     - Connected: {'✓' if details['connected'] else '✗'}")
        print(f"     - App authenticated: {'✓' if details['app_auth'] else '✗'}")
        print(f"     - Account authenticated: {'✓' if details['account_auth'] else '✗'}")
        print(f"     - Symbols loaded: {details['symbols']}")
        print(f"\n💡 Your ACCESS_TOKEN is working correctly!")
        return True
    else:
        print(f"  ❌ FAILED: {result['error']}")
        if "invalid" in str(result['error']).lower() or "auth" in str(result['error']).lower():
            print(f"\n💡 This suggests your ACCESS_TOKEN may be expired.")
            print(f"   Try refreshing it from your cTrader application.")
        return False

if __name__ == "__main__":
    try:
        success = test_credentials()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⏹️  Test interrupted by user")
        sys.exit(1)