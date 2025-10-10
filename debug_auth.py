#!/usr/bin/env python3
"""
Debug authentication script for cTrader API
Provides detailed logging of the authentication process
"""

import os
import sys
import time
from twisted.internet import reactor
from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *
from ctrader_open_api.messages.OpenApiMessages_pb2 import *
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import *
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class AuthDebugBot:
    """Debug bot to test authentication step by step"""
    
    def __init__(self):
        # Load credentials from .env
        self.client_id = os.getenv('CLIENT_ID')
        self.client_secret = os.getenv('CLIENT_SECRET')
        self.access_token = os.getenv('ACCESS_TOKEN')
        self.account_id = int(os.getenv('ACCOUNT_ID', '0'))
        self.host_type = os.getenv('HOST', 'demo').lower()
        
        print(f"Credentials check:")
        print(f"  CLIENT_ID: {'✓' if self.client_id else '✗'} ({'*' * 10}...{self.client_id[-5:] if self.client_id else 'None'})")
        print(f"  CLIENT_SECRET: {'✓' if self.client_secret else '✗'} ({'*' * 20}...{self.client_secret[-5:] if self.client_secret else 'None'})")
        print(f"  ACCESS_TOKEN: {'✓' if self.access_token else '✗'} ({'*' * 20}...{self.access_token[-5:] if self.access_token else 'None'})")
        print(f"  ACCOUNT_ID: {'✓' if self.account_id else '✗'} ({self.account_id})")
        print(f"  HOST: {self.host_type}")
        
        # State tracking
        self.client = None
        self.is_connected = False
        self.is_app_authenticated = False
        self.is_account_authenticated = False
        self.symbols_count = 0
        
        self.start_time = time.time()
        
    def start(self):
        """Start the bot and connect"""
        host = "demo.ctraderapi.com" if self.host_type == "demo" else "live.ctraderapi.com"
        port = 5035
        
        print(f"\n🔗 Connecting to {host}:{port}...")
        
        self.client = Client(host, port, TcpProtocol)
        self.client.setConnectedCallback(self._on_connected)
        self.client.setDisconnectedCallback(self._on_disconnected)
        self.client.setMessageReceivedCallback(self._on_message)
        self.client.startService()
        
        # Set a timeout to stop the reactor
        reactor.callLater(30, self._timeout)
        
    def _timeout(self):
        """Called when timeout is reached"""
        elapsed = time.time() - self.start_time
        print(f"\n⏰ Timeout reached after {elapsed:.1f} seconds")
        print("\nFinal status:")
        print(f"  Connected: {'✓' if self.is_connected else '✗'}")
        print(f"  App authenticated: {'✓' if self.is_app_authenticated else '✗'}")
        print(f"  Account authenticated: {'✓' if self.is_account_authenticated else '✗'}")
        print(f"  Symbols loaded: {self.symbols_count}")
        
        if not self.is_account_authenticated:
            print("\n❌ ISSUE: Account authentication failed!")
            print("   This typically means:")
            print("   1. ACCESS_TOKEN is expired or invalid")
            print("   2. ACCOUNT_ID doesn't match the token")
            print("   3. Network/API connectivity issues")
            print("\n💡 Try refreshing your ACCESS_TOKEN from cTrader")
        
        reactor.stop()
        
    def _on_connected(self, client):
        """Called when connected to server"""
        elapsed = time.time() - self.start_time
        print(f"✅ Connected! ({elapsed:.1f}s)")
        self.is_connected = True
        
        # Send application authentication request
        print("\n🔐 Step 1: Authenticating application...")
        request = ProtoOAApplicationAuthReq()
        request.clientId = self.client_id
        request.clientSecret = self.client_secret
        
        deferred = client.send(request)
        deferred.addErrback(self._on_error)
        
    def _on_disconnected(self, client, reason):
        """Called when disconnected from server"""
        elapsed = time.time() - self.start_time
        print(f"❌ Disconnected: {reason} ({elapsed:.1f}s)")
        self.is_connected = False
        
    def _on_error(self, failure):
        """Called when an error occurs"""
        elapsed = time.time() - self.start_time
        print(f"❌ Error: {failure} ({elapsed:.1f}s)")
        
    def _on_message(self, client, message):
        """Handle incoming messages"""
        elapsed = time.time() - self.start_time
        
        try:
            # Application authentication response
            if message.payloadType == ProtoOAApplicationAuthRes().payloadType:
                print(f"✅ Application authenticated! ({elapsed:.1f}s)")
                self.is_app_authenticated = True
                self._authenticate_account()
            
            # Account authentication response
            elif message.payloadType == ProtoOAAccountAuthRes().payloadType:
                print(f"✅ Account authenticated! ({elapsed:.1f}s)")
                self.is_account_authenticated = True
                self._request_symbols()
            
            # Symbols list response
            elif message.payloadType == ProtoOASymbolsListRes().payloadType:
                response = Protobuf.extract(message)
                self.symbols_count = len(response.symbol)
                print(f"✅ Symbols loaded: {self.symbols_count} symbols ({elapsed:.1f}s)")
                
                if self.symbols_count > 0:
                    print(f"\n🎉 SUCCESS! Bot fully initialized in {elapsed:.1f} seconds")
                    print(f"   - Application authenticated: ✓")
                    print(f"   - Account authenticated: ✓") 
                    print(f"   - Symbols loaded: {self.symbols_count}")
                    reactor.stop()
            
            # Error responses
            elif message.payloadType == ProtoOAErrorRes().payloadType:
                error_response = Protobuf.extract(message)
                print(f"❌ API Error: {error_response.description} (Code: {error_response.errorCode}) ({elapsed:.1f}s)")
                
        except Exception as e:
            print(f"❌ Error processing message: {e} ({elapsed:.1f}s)")
    
    def _authenticate_account(self):
        """Authenticate trading account"""
        elapsed = time.time() - self.start_time
        print(f"\n🔐 Step 2: Authenticating account {self.account_id}... ({elapsed:.1f}s)")
        
        request = ProtoOAAccountAuthReq()
        request.ctidTraderAccountId = self.account_id
        request.accessToken = self.access_token
        
        deferred = self.client.send(request)
        deferred.addErrback(self._on_error)
    
    def _request_symbols(self):
        """Request available symbols"""
        elapsed = time.time() - self.start_time
        print(f"\n📊 Step 3: Requesting symbols... ({elapsed:.1f}s)")
        
        request = ProtoOASymbolsListReq()
        request.ctidTraderAccountId = self.account_id
        
        deferred = self.client.send(request)
        deferred.addErrback(self._on_error)


def main():
    print("="*60)
    print("  cTrader Authentication Debug")
    print("="*60)
    
    try:
        bot = AuthDebugBot()
        bot.start()
        reactor.run()
    except KeyboardInterrupt:
        print("\n\n⏹️  Interrupted by user")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")


if __name__ == "__main__":
    main()