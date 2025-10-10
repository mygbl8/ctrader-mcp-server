#!/usr/bin/env python3
"""
Synchronous cTrader authentication utility
Handles authentication before starting the main async server
"""

import os
import time
from twisted.internet import reactor
from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *
from ctrader_open_api.messages.OpenApiMessages_pb2 import *
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import *
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class SyncCTraderAuth:
    """Synchronous cTrader authentication"""
    
    def __init__(self):
        # Load credentials from .env
        self.client_id = os.getenv('CLIENT_ID')
        self.client_secret = os.getenv('CLIENT_SECRET')
        self.access_token = os.getenv('ACCESS_TOKEN')
        self.account_id = int(os.getenv('ACCOUNT_ID', '0'))
        self.host_type = os.getenv('HOST', 'demo').lower()
        
        # Validate credentials
        if not all([self.client_id, self.client_secret, self.access_token, self.account_id]):
            raise ValueError("Missing credentials in .env file")
        
        # State
        self.client = None
        self.is_connected = False
        self.is_app_authenticated = False
        self.is_account_authenticated = False
        self.symbols = {}
        self.authenticated = False
        self.error = None
        
    def authenticate(self, timeout=30):
        """Authenticate synchronously with timeout"""
        
        def run_auth():
            host = "demo.ctraderapi.com" if self.host_type == "demo" else "live.ctraderapi.com"
            
            self.client = Client(host, 5035, TcpProtocol)
            self.client.setConnectedCallback(self._on_connected)
            self.client.setDisconnectedCallback(self._on_disconnected)
            self.client.setMessageReceivedCallback(self._on_message)
            
            # Set timeout
            reactor.callLater(timeout, self._timeout)
            
            self.client.startService()
            reactor.run()
        
        try:
            run_auth()
        except Exception as e:
            self.error = str(e)
        
        if self.error:
            raise Exception(f"Authentication failed: {self.error}")
        
        if not self.authenticated:
            raise Exception("Authentication timed out")
        
        return True
    
    def _timeout(self):
        """Handle authentication timeout"""
        self.error = "Authentication timeout"
        reactor.stop()
    
    def _on_connected(self, client):
        """Called when connected to server"""
        self.is_connected = True
        
        # Send application authentication request
        request = ProtoOAApplicationAuthReq()
        request.clientId = self.client_id
        request.clientSecret = self.client_secret
        
        deferred = client.send(request)
        deferred.addErrback(self._on_error)
    
    def _on_disconnected(self, client, reason):
        """Called when disconnected from server"""
        if not self.authenticated:
            self.error = f"Disconnected before authentication: {reason}"
        reactor.stop()
    
    def _on_error(self, failure):
        """Called when an error occurs"""
        self.error = f"Request error: {failure}"
        reactor.stop()
    
    def _on_message(self, client, message):
        """Handle incoming messages"""
        try:
            # Application authentication response
            if message.payloadType == ProtoOAApplicationAuthRes().payloadType:
                self.is_app_authenticated = True
                self._authenticate_account()
            
            # Account authentication response
            elif message.payloadType == ProtoOAAccountAuthRes().payloadType:
                self.is_account_authenticated = True
                self._request_symbols()
            
            # Symbols list response
            elif message.payloadType == ProtoOASymbolsListRes().payloadType:
                self._handle_symbols_response(message)
                # Authentication complete
                self.authenticated = True
                reactor.stop()
            
            # Error response
            elif message.payloadType == ProtoOAErrorRes().payloadType:
                error_response = Protobuf.extract(message)
                self.error = f"API Error: {error_response.description}"
                reactor.stop()
                
        except Exception as e:
            self.error = f"Message processing error: {e}"
            reactor.stop()
    
    def _authenticate_account(self):
        """Authenticate trading account"""
        request = ProtoOAAccountAuthReq()
        request.ctidTraderAccountId = self.account_id
        request.accessToken = self.access_token
        
        deferred = self.client.send(request)
        deferred.addErrback(self._on_error)
    
    def _request_symbols(self):
        """Request available symbols"""
        request = ProtoOASymbolsListReq()
        request.ctidTraderAccountId = self.account_id
        
        deferred = self.client.send(request)
        deferred.addErrback(self._on_error)
    
    def _handle_symbols_response(self, message):
        """Process symbols list"""
        response = Protobuf.extract(message)
        for symbol in response.symbol:
            self.symbols[symbol.symbolName] = {
                'id': symbol.symbolId,
                'name': symbol.symbolName,
                'enabled': symbol.enabled,
                'base_currency': getattr(symbol, 'baseAsset', ''),
                'quote_currency': getattr(symbol, 'quoteAsset', ''),
                'digits': getattr(symbol, 'digits', 5),
                'pip_size': getattr(symbol, 'pipSize', 0.00001),
                'lot_size': getattr(symbol, 'lotSize', 100000),
                'step_volume': getattr(symbol, 'stepVolume', 10000),
                'max_volume': getattr(symbol, 'maxVolume', 100000000),
                'min_volume': getattr(symbol, 'minVolume', 10000),
            }


def test_auth():
    """Test authentication"""
    print("Testing cTrader authentication...")
    try:
        auth = SyncCTraderAuth()
        auth.authenticate(timeout=15)
        print(f"✓ Authentication successful! Loaded {len(auth.symbols)} symbols")
        return auth
    except Exception as e:
        print(f"✗ Authentication failed: {e}")
        return None


if __name__ == "__main__":
    test_auth()