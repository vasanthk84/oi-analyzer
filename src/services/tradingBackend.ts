// ============================================
// COMPLETE INTEGRATION PACKAGE
// File: src/services/tradingBackend.ts
// 
// This is your SINGLE service layer that handles everything.
// Drop this into your React app and start using it immediately.
// ============================================

export interface Position {
  tradingsymbol: string;
  quantity: number;
  average_price: number;
  last_price: number;
  mtm?: number;
  pnl?: number;
  product: string;
  exchange: string;
  orderTime?: string;
}

export interface StrangleRecommendation {
  rec_call: number;
  rec_put: number;
  est_credit: number;
  call_greeks: {
    delta: number;
    gamma: number;
    theta: number;
    vega: number;
  };
  put_greeks: {
    delta: number;
    gamma: number;
    theta: number;
    vega: number;
  };
  call_stats: {
    ok: boolean;
    buy_qty: number;
    sell_qty: number;
  };
  put_stats: {
    ok: boolean;
    buy_qty: number;
    sell_qty: number;
  };
}

export interface MarketIntel {
  regime: string;
  regime_bias: string;
  iv_rank: number;
  iv_status: string;
  dte_msg: string;
  rsi: number;
}

export interface AnalysisData {
  timestamp: string;
  nifty_spot: number;
  vix: {
    value: number;
    change: number;
  };
  greeks: {
    delta: number;
    gamma: number;
    theta: number;
    vega: number;
  };
  skew: {
    value: number;
    put_price: number;
    call_price: number;
  };
  metrics: {
    max_pain: number;
    pcr: number;
    support: number;
    resistance: number;
  };
  strangle_intel: {
    conservative: StrangleRecommendation;
    moderate: StrangleRecommendation;
    aggressive: StrangleRecommendation;
  };
  market_intel: MarketIntel;
}

export interface ExecutionResult {
  success: boolean;
  message: string;
  callOrder?: {
    orderId: string;
    symbol: string;
    price: number;
    quantity: number;
  };
  putOrder?: {
    orderId: string;
    symbol: string;
    price: number;
    quantity: number;
  };
  timestamp: string;
  error?: string;
}

// ============================================
// BACKEND CONFIGURATION
// ============================================

const BACKENDS = {
  // Python Backend - Analytics & Intelligence
  python: {
    url: 'http://localhost:8000',
    enabled: true,
    features: ['analytics', 'greeks', 'regime_detection', 'historical_analysis']
  },
  
  // Go Backend - Execution & Position Management
  go: {
    url: 'http://localhost:8080',
    enabled: false, // Set to true when Go API is running
    features: ['execution', 'position_management', 'risk_management', 'auto_trading']
  }
};

// ============================================
// MAIN TRADING BACKEND SERVICE
// ============================================

class TradingBackendService {
  private pythonUrl = BACKENDS.python.url;
  private goUrl = BACKENDS.go.url;
  private useGoAPI = BACKENDS.go.enabled;

  // ==========================================
  // ANALYTICS - Always use Python (Best Intelligence)
  // ==========================================

  async getAnalysis(): Promise<AnalysisData> {
    try {
      const response = await fetch(`${this.pythonUrl}/analyze`);
      if (!response.ok) throw new Error(`Analysis failed: ${response.status}`);
      return await response.json();
    } catch (error) {
      console.error('❌ Analysis fetch failed:', error);
      throw error;
    }
  }

  async getHistoricalAnalysis() {
    try {
      const response = await fetch(`${this.pythonUrl}/historical_analysis`);
      return await response.json();
    } catch (error) {
      console.error('❌ Historical analysis failed:', error);
      return null;
    }
  }

  async saveEODData() {
    try {
      const response = await fetch(`${this.pythonUrl}/update_daily_ohlc`, {
        method: 'POST'
      });
      return await response.json();
    } catch (error) {
      console.error('❌ EOD save failed:', error);
      throw error;
    }
  }

  // ==========================================
  // POSITIONS - Smart Routing
  // Uses Go if available (better tracking), falls back to Python
  // ==========================================

  async getPositions(): Promise<{ positions: Position[]; total_mtm: number }> {
    try {
      if (this.useGoAPI) {
        // Go API provides better position tracking with entry/exit prices
        const response = await fetch(`${this.goUrl}/api/positions`);
        const data = await response.json();
        
        if (data.success) {
          // Calculate MTM for Go API responses
          const positions = data.positions.map((p: any) => ({
            tradingsymbol: p.tradingSymbol,
            quantity: p.qty,
            average_price: p.avg,
            last_price: p.ltp,
            mtm: p.pnL,
            product: p.product,
            exchange: p.exchange,
            orderTime: p.entryTime
          }));
          
          return {
            positions,
            total_mtm: data.totalPnL
          };
        }
      }

      // Fallback to Python API
      const response = await fetch(`${this.pythonUrl}/positions`);
      const data = await response.json();
      
      // Calculate MTM manually for Python responses
      const positions = (data.data || []).map((p: any) => {
        const mtm = (p.last_price - p.average_price) * p.quantity;
        return {
          ...p,
          mtm
        };
      });
      
      const total_mtm = positions.reduce((sum: number, p: Position) => sum + (p.mtm || 0), 0);
      
      return { positions, total_mtm };
      
    } catch (error) {
      console.error('❌ Positions fetch failed:', error);
      return { positions: [], total_mtm: 0 };
    }
  }

  // Real-time position streaming via SSE
  subscribeToPositions(callback: (data: { positions: Position[]; total_mtm: number }) => void): () => void {
    const apiUrl = this.useGoAPI ? `${this.goUrl}/api/positions/stream` : `${this.pythonUrl}/positions/stream`;
    
    const eventSource = new EventSource(apiUrl);
    
    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        
        // Normalize data format between Go and Python
        if (this.useGoAPI && data.positions) {
          const positions = data.positions.map((p: any) => ({
            tradingsymbol: p.tradingSymbol || p.symbol,
            quantity: p.qty || p.quantity,
            average_price: p.avg || p.average_price,
            last_price: p.ltp || p.last_price,
            mtm: p.pnL || p.mtm,
            product: p.product,
            exchange: p.exchange
          }));
          callback({ positions, total_mtm: data.totalPnL });
        } else {
          // Python format
          callback(data);
        }
      } catch (error) {
        console.error('❌ Position stream parse error:', error);
      }
    };

    eventSource.onerror = (error) => {
      console.error('❌ Position stream error:', error);
      // Auto-reconnect is handled by EventSource
    };

    // Return cleanup function
    return () => {
      eventSource.close();
    };
  }

  // ==========================================
  // EXECUTION - Smart Routing with Fallback
  // ==========================================

  async executeStrangle(
    callStrike: number,
    putStrike: number,
    quantity: number,
    options: {
      profile?: 'conservative' | 'moderate' | 'aggressive';
      autoTrade?: boolean;
    } = {}
  ): Promise<ExecutionResult> {
    const { profile = 'moderate', autoTrade = false } = options;

    try {
      // Build symbol names (format: NIFTY25DEC24500CE)
      const symbols = this.buildSymbols(callStrike, putStrike);

      if (this.useGoAPI) {
        // Use Go API for robust execution
        console.log('🚀 Executing via Go API...');
        return await this.executeViaGo(symbols.callSymbol, symbols.putSymbol, quantity, autoTrade);
      } else {
        // Use Python API for execution
        console.log('🚀 Executing via Python API...');
        return await this.executeViaPython(callStrike, putStrike, quantity);
      }
      
    } catch (error) {
      console.error('❌ Execution failed:', error);
      return {
        success: false,
        message: 'Execution failed',
        error: error instanceof Error ? error.message : 'Unknown error',
        timestamp: new Date().toISOString()
      };
    }
  }

  private async executeViaGo(callSymbol: string, putSymbol: string, quantity: number, autoTrade: boolean): Promise<ExecutionResult> {
    const response = await fetch(`${this.goUrl}/api/strangle/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        callSymbol,
        putSymbol,
        quantity,
        autoTrade, // Enable Go's automated risk management
        orderType: 'MARKET',
        product: 'NRML'
      })
    });

    if (!response.ok) {
      throw new Error(`Go API error: ${response.status}`);
    }

    const data = await response.json();
    return data;
  }

  private async executeViaPython(callStrike: number, putStrike: number, quantity: number): Promise<ExecutionResult> {
    const response = await fetch(`${this.pythonUrl}/execute_strangle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        call_strike: callStrike,
        put_strike: putStrike,
        qty: quantity
      })
    });

    if (!response.ok) {
      throw new Error(`Python API error: ${response.status}`);
    }

    const data = await response.json();
    
    // Normalize response format
    return {
      success: data.status === 'success',
      message: data.message || 'Executed successfully',
      timestamp: new Date().toISOString()
    };
  }

  // ==========================================
  // POSITION MANAGEMENT - Only available with Go API
  // ==========================================

  async closePosition(tradingSymbol: string, quantity: number): Promise<ExecutionResult> {
    if (!this.useGoAPI) {
      return {
        success: false,
        message: 'Position management requires Go API. Please enable it in configuration.',
        timestamp: new Date().toISOString()
      };
    }

    try {
      const response = await fetch(`${this.goUrl}/api/position/close`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tradingSymbol,
          quantity,
          orderType: 'MARKET'
        })
      });

      return await response.json();
    } catch (error) {
      console.error('❌ Close position failed:', error);
      throw error;
    }
  }

  async closeAllPositions(): Promise<ExecutionResult> {
    if (!this.useGoAPI) {
      return {
        success: false,
        message: 'Bulk operations require Go API',
        timestamp: new Date().toISOString()
      };
    }

    try {
      const response = await fetch(`${this.goUrl}/api/positions/close-all`, {
        method: 'POST'
      });

      return await response.json();
    } catch (error) {
      console.error('❌ Close all failed:', error);
      throw error;
    }
  }

  // ==========================================
  // SYSTEM STATUS
  // ==========================================

  async getSystemStatus() {
    const status = {
      python: { available: false, url: this.pythonUrl },
      go: { available: false, url: this.goUrl },
      activeBackend: this.useGoAPI ? 'go' : 'python',
      features: {
        analytics: true,
        execution: true,
        positionManagement: this.useGoAPI,
        riskManagement: this.useGoAPI,
        autoTrading: this.useGoAPI
      }
    };

    // Test Python
    try {
      const response = await fetch(`${this.pythonUrl}/analyze`, { 
        method: 'HEAD',
        signal: AbortSignal.timeout(2000) 
      });
      status.python.available = response.ok;
    } catch (error) {
      console.warn('⚠️ Python backend unavailable');
    }

    // Test Go
    if (this.useGoAPI) {
      try {
        const response = await fetch(`${this.goUrl}/health`, {
          method: 'GET',
          signal: AbortSignal.timeout(2000)
        });
        status.go.available = response.ok;
      } catch (error) {
        console.warn('⚠️ Go backend unavailable');
      }
    }

    return status;
  }

  // ==========================================
  // HELPER METHODS
  // ==========================================

  private buildSymbols(callStrike: number, putStrike: number) {
    // Get next expiry date
    const today = new Date();
    const dayOfWeek = today.getDay();
    
    // Find next Thursday (weekly expiry) or Tuesday before Sept 2025
    const daysUntilExpiry = dayOfWeek === 4 ? 0 : (4 - dayOfWeek + 7) % 7;
    const expiry = new Date(today);
    expiry.setDate(today.getDate() + daysUntilExpiry);

    const year = expiry.getFullYear().toString().slice(-2);
    const month = expiry.toLocaleString('en-US', { month: 'short' }).toUpperCase();
    const day = expiry.getDate();

    // Format: NIFTY25DEC24500CE
    const callSymbol = `NIFTY${year}${month}${day}${callStrike}CE`;
    const putSymbol = `NIFTY${year}${month}${day}${putStrike}PE`;

    return { callSymbol, putSymbol };
  }

  // Configuration methods
  enableGoAPI(enable: boolean) {
    this.useGoAPI = enable && BACKENDS.go.enabled;
    console.log(`🔧 Go API ${this.useGoAPI ? 'enabled' : 'disabled'}`);
  }

  isGoAPIEnabled() {
    return this.useGoAPI;
  }
}

// ==========================================
// EXPORT SINGLETON INSTANCE
// ==========================================

export const tradingBackend = new TradingBackendService();

// ==========================================
// USAGE EXAMPLES
// ==========================================

/*

// 1. Get market analysis (always uses Python)
const analysis = await tradingBackend.getAnalysis();
console.log('Strike Recommendation:', analysis.strangle_intel.moderate);

// 2. Execute strangle (smart routing)
const result = await tradingBackend.executeStrangle(24500, 23500, 50, {
  profile: 'moderate',
  autoTrade: false // Set true to enable Go's auto-management
});

if (result.success) {
  console.log('✅ Executed:', result.message);
} else {
  console.error('❌ Failed:', result.error);
}

// 3. Get positions (one-time)
const { positions, total_mtm } = await tradingBackend.getPositions();
console.log('Total MTM:', total_mtm);

// 4. Subscribe to real-time positions
const unsubscribe = tradingBackend.subscribeToPositions((data) => {
  console.log('Live MTM:', data.total_mtm);
  // Update your React state here
});

// Later: cleanup
unsubscribe();

// 5. Close a specific position (requires Go API)
await tradingBackend.closePosition('NIFTY25DEC24500CE', 50);

// 6. Close all positions (requires Go API)
await tradingBackend.closeAllPositions();

// 7. Check system status
const status = await tradingBackend.getSystemStatus();
console.log('Python:', status.python.available);
console.log('Go:', status.go.available);
console.log('Features:', status.features);

*/