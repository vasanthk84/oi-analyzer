const express = require('express');
const axios = require('axios');
const app = express();
const PORT = 3000;

app.use(express.json());

// Add position caching
let lastKnownPositions = [];
let lastPositionUpdate = null;

class CircuitBreaker {
    constructor(name, failureThreshold = 5, resetTimeout = 60000) {
        this.name = name;
        this.failureCount = 0;
        this.failureThreshold = failureThreshold;
        this.resetTimeout = resetTimeout;
        this.state = 'CLOSED'; // CLOSED, OPEN, HALF_OPEN
        this.nextAttempt = Date.now();
    }

    async execute(fn) {
        if (this.state === 'OPEN') {
            if (Date.now() < this.nextAttempt) {
                throw new Error(`Circuit breaker [${this.name}] is OPEN`);
            }
            this.state = 'HALF_OPEN';
        }

        try {
            const result = await fn();
            this.onSuccess();
            return result;
        } catch (error) {
            this.onFailure();
            throw error;
        }
    }

    onSuccess() {
        this.failureCount = 0;
        this.state = 'CLOSED';
    }

    onFailure() {
        this.failureCount++;
        if (this.failureCount >= this.failureThreshold) {
            this.state = 'OPEN';
            this.nextAttempt = Date.now() + this.resetTimeout;
            console.error(`⚠️ Circuit breaker [${this.name}] OPENED after ${this.failureCount} failures`);
        }
    }
}

// ============================================
// BACKEND CONFIGURATION (Hybrid Architecture)
// ============================================

const BACKENDS = {
    python: {
        url: 'http://127.0.0.1:8000',
        enabled: true,
        features: ['analytics', 'greeks', 'regime_detection', 'historical_analysis']
    },
    go: {
        url: 'http://127.0.0.1:8080',
        enabled: true, // Set to TRUE when Go API is running
        features: ['execution', 'position_management', 'risk_management', 'auto_trading']
    }
};

const pythonBreaker = new CircuitBreaker('Python', 3, 30000);
const goBreaker = new CircuitBreaker('Go', 3, 30000);

// ============================================
// HEALTH CHECK - Verify Go API is Running
// ============================================

async function checkGoAPI() {
    try {
        const response = await axios.get(`${BACKENDS.go.url}/health`, { timeout: 2000 });
        if (response.data.status === 'ok') {
            console.log('✅ Go API Connected | Spot:', response.data.spot);
            return true;
        }
    } catch (error) {
        console.error('❌ Go API Unavailable:', error.message);
        return false;
    }
}


// Retry with exponential backoff
async function retryWithBackoff(fn, maxRetries = 3) {
    for (let attempt = 1; attempt <= maxRetries; attempt++) {
        try {
            return await fn();
        } catch (error) {
            if (attempt === maxRetries) throw error;
            
            const delay = Math.min(1000 * Math.pow(2, attempt), 10000);
            console.log(`Retry ${attempt}/${maxRetries} after ${delay}ms...`);
            await new Promise(resolve => setTimeout(resolve, delay));
        }
    }
}


// Smart routing function
function getBackendUrl(feature) {
    // Analytics always goes to Python (best intelligence)
    if (['analytics', 'greeks', 'historical'].includes(feature)) {
        return BACKENDS.python.url;
    }

    // Execution: Use Go if available, fallback to Python
    if (feature === 'execution') {
        return BACKENDS.go.enabled ? BACKENDS.go.url : BACKENDS.python.url;
    }


    return BACKENDS.python.url;
}

// ============================================
// PROXY ENDPOINTS (Smart Routing)
// ============================================

// Analytics - Always Python
app.get('/api/data', async (req, res) => {
    try {
        const response = await axios.get(`${BACKENDS.python.url}/analyze`);
        res.json(response.data);
    } catch (error) {
        console.error('❌ Analytics failed:', error.message);
        res.status(502).json({ error: "Python Backend Offline" });
    }
});

// Historical Analysis - Always Python
app.get('/api/history', async (req, res) => {
    try {
        const response = await axios.get(`${BACKENDS.python.url}/historical_analysis`);
        res.json(response.data);
    } catch (error) {
        console.error('❌ History failed:', error.message);
        res.status(502).json({ error: "Backend Offline" });
    }
});

// Save Daily Data - Always Python
app.post('/api/update_daily', async (req, res) => {
    try {
        const response = await axios.post(`${BACKENDS.python.url}/update_daily_ohlc`);
        res.json(response.data);
    } catch (error) {
        console.error('❌ EOD save failed:', error.message);
        res.status(502).json({ error: "Backend Offline" });
    }
});



// ============================================
// POSITIONS - Use Go API (Advanced Features)
// ============================================

// REPLACE /positions endpoint with this:
app.get('/positions', async (req, res) => {
    try {
        console.log('📊 Fetching positions with circuit breaker...');

        // Try Go API with circuit breaker
        try {
            const goResponse = await goBreaker.execute(() =>
                retryWithBackoff(() =>
                    axios.get(`${BACKENDS.go.url}/api/positions`, { timeout: 5000 })
                )
            );

            return res.json({
                ...goResponse.data,
                source: 'go_api',
                reliability: 'primary'
            });

        } catch (goError) {
            console.warn('⚠️ Go API failed, falling back to Python...');

            // Fallback to Python with circuit breaker
            try {
                const pythonResponse = await pythonBreaker.execute(() =>
                    retryWithBackoff(() =>
                        axios.get(`${BACKENDS.python.url}/positions`, { timeout: 5000 })
                    )
                );

                return res.json({
                    ...pythonResponse.data,
                    source: 'python_fallback',
                    reliability: 'backup',
                    warning: 'Primary system unavailable'
                });

            } catch (pythonError) {
                console.error('❌ Both backends failed!');
                
                // Return cached data if available
                if (lastKnownPositions) {
                    return res.json({
                        success: true,
                        data: lastKnownPositions,
                        source: 'cache',
                        reliability: 'degraded',
                        warning: 'Using cached data - systems unavailable',
                        cached_at: lastPositionUpdate
                    });
                }

                // Ultimate fallback - empty but valid response
                return res.status(503).json({
                    success: false,
                    data: [],
                    total_mtm: 0,
                    source: 'none',
                    error: 'All position sources unavailable',
                    timestamp: new Date().toISOString()
                });
            }
        }

    } catch (error) {
        console.error('❌ Critical error in position handler:', error);
        res.status(500).json({
            success: false,
            data: [],
            error: error.message
        });
    }
});

// ============================================
// EXECUTE STRANGLE - Use Go API (Intelligent Execution)
// ============================================

app.post('/execute_strangle', async (req, res) => {
    try {
        const { call_strike, put_strike, qty = 75, profile = 'moderate', autoTrade = true } = req.body;

        console.log('🚀 Executing Strangle via Go API...');
        console.log(`   Call: ${call_strike} | Put: ${put_strike} | Qty: ${qty} | Auto: ${autoTrade}`);

        // ✅ FIXED: Send data in Go API's expected format
        const response = await axios.post(`${BACKENDS.go.url}/api/strangle/execute`, {
            call_strike: parseFloat(call_strike),
            put_strike: parseFloat(put_strike),
            quantity: parseInt(qty),
            autoTrade: autoTrade  // Enable Go's risk management
        });

        console.log('✅ Execution Success:', response.data.message);

        // Return enhanced response with metadata
        res.json({
            status: 'success',
            message: response.data.message,
            execution_details: {
                call_symbol: response.data.call_symbol,
                put_symbol: response.data.put_symbol,
                call_entry: response.data.call_entry_price,
                put_entry: response.data.put_entry_price,
                total_credit: response.data.estimated_credit,
                auto_management: response.data.auto_management
            },
            metadata: response.data.metadata,
            backend: 'go_api'
        });

    } catch (error) {
        console.error('❌ Execution failed:', error.message);

        // Provide detailed error information
        const errorMsg = error.response?.data?.error || error.message;
        res.status(502).json({
            status: 'error',
            message: `Execution failed: ${errorMsg}`,
            backend: 'go_api',
            timestamp: new Date().toISOString()
        });
    }
});

// ============================================
// POSITION MANAGEMENT - Go API Only
// ============================================

app.post('/close_position', async (req, res) => {
    try {
        const { tradingSymbol, quantity } = req.body;

        console.log(`🔴 Closing position: ${tradingSymbol} (${quantity} qty)`);

        const response = await axios.post(`${BACKENDS.go.url}/api/position/close`, {
            tradingSymbol,
            quantity: parseInt(quantity)
        });

        res.json({
            success: true,
            message: response.data.message,
            realized_pnl: response.data.realized_pnl,
            backend: 'go_api'
        });

    } catch (error) {
        console.error('❌ Close position failed:', error.message);
        res.status(502).json({
            success: false,
            message: error.response?.data?.error || error.message
        });
    }
});

app.post('/close_all_positions', async (req, res) => {
    try {
        console.log('🔴 Closing ALL positions...');

        const response = await axios.post(`${BACKENDS.go.url}/api/positions/close-all`);

        res.json({
            success: true,
            message: response.data.message,
            total_pnl: response.data.total_pnl,
            closed_count: response.data.closed_count,
            backend: 'go_api'
        });

    } catch (error) {
        console.error('❌ Close all failed:', error.message);
        res.status(502).json({
            success: false,
            message: error.response?.data?.error || error.message
        });
    }
});

// ============================================
// SYSTEM STATUS - Check Both Backends
// ============================================

app.get('/api/system_status', async (req, res) => {
    const status = {
        python: { available: false, url: BACKENDS.python.url },
        go: { available: false, url: BACKENDS.go.url, features: {} },
        activeBackend: BACKENDS.go.enabled ? 'go' : 'python',
        features: {
            analytics: true,
            execution: false,
            positionManagement: false,
            riskManagement: false,
            autoTrading: false
        },
        timestamp: new Date().toISOString()
    };

    // Test Python
    try {
        await axios.get(`${BACKENDS.python.url}/analyze`, { timeout: 2000 });
        status.python.available = true;
        status.features.analytics = true;
    } catch (error) {
        console.warn('⚠️ Python backend unavailable');
    }

    // Test Go
    try {
        const goResponse = await axios.get(`${BACKENDS.go.url}/health`, { timeout: 2000 });
        status.go.available = true;
        status.go.features = goResponse.data.features;

        // Enable features if Go is available
        if (status.go.available) {
            status.features.execution = true;
            status.features.positionManagement = true;
            status.features.riskManagement = true;
            status.features.autoTrading = true;
        }
    } catch (error) {
        console.warn('⚠️ Go backend unavailable');
    }

    res.json(status);
});

// ============================================
// HELPER FUNCTIONS
// ============================================

function buildSymbols(callStrike, putStrike) {
    const today = new Date();
    const dayOfWeek = today.getDay();
    const daysUntilExpiry = dayOfWeek === 4 ? 0 : (4 - dayOfWeek + 7) % 7;
    const expiry = new Date(today);
    expiry.setDate(today.getDate() + daysUntilExpiry);

    const year = expiry.getFullYear().toString().slice(-2);
    const month = expiry.toLocaleString('en-US', { month: 'short' }).toUpperCase();
    const day = expiry.getDate();

    return {
        callSymbol: `NIFTY${year}${month}${day}${callStrike}CE`,
        putSymbol: `NIFTY${year}${month}${day}${putStrike}PE`
    };
}
// ============================================

const getHtml = () => `
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Nifty Option Master</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation"></script>
    <style>
        body { background-color: #0f172a; color: #e2e8f0; font-family: 'Inter', sans-serif; }
        .glass-panel { background: rgba(30, 41, 59, 0.7); backdrop-filter: blur(10px); border: 1px solid rgba(255,255,255,0.1); }
        .stat-label { font-size: 0.7rem; text-transform: uppercase; color: #94a3b8; letter-spacing: 0.05em; }
        
        .tooltip { 
            visibility: hidden; position: absolute; z-index: 50; background: #1e293b; border: 1px solid #475569; padding: 12px; border-radius: 8px; font-size: 0.75rem; width: 220px; top: 100%; margin-top: 8px; right: 0; white-space: normal; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.6); opacity: 0; transition: opacity 0.2s; pointer-events: none; 
        }
        .has-tooltip:hover .tooltip { visibility: visible; opacity: 1; }
        
        .toggle-checkbox:checked { right: 0; border-color: #68D391; }
        .toggle-checkbox:checked + .toggle-label { background-color: #68D391; }
        
        .flow-bar { height: 4px; width: 100%; background: #334155; border-radius: 2px; overflow: hidden; display: flex; margin-top: 4px; }
        .flow-buy { background: #4ade80; height: 100%; }
        .flow-sell { background: #f87171; height: 100%; }

        /* Scrollable Positions Table */
        .positions-scroll-container {
            max-height: 400px;
            overflow-y: auto;
            overflow-x: hidden;
        }
        .positions-scroll-container::-webkit-scrollbar {
            width: 8px;
        }
        .positions-scroll-container::-webkit-scrollbar-track {
            background: #1e293b;
            border-radius: 4px;
        }
        .positions-scroll-container::-webkit-scrollbar-thumb {
            background: #475569;
            border-radius: 4px;
        }
        .positions-scroll-container::-webkit-scrollbar-thumb:hover {
            background: #64748b;
        }
        
        /* New Intel Animations */
        @keyframes pulse-soft { 0% { opacity: 0.8; } 50% { opacity: 1; } 100% { opacity: 0.8; } }
        .live-dot { height: 6px; width: 6px; border-radius: 50%; display: inline-block; margin-right: 4px; animation: pulse-soft 2s infinite; }
    </style>
</head>
<body class="p-4 md:p-8 max-w-7xl mx-auto pb-20">

    <!-- Header -->
    <div class="flex justify-between items-center mb-6">
        <div>
            <h1 class="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-indigo-400 to-cyan-400">OPTION MASTER <span class="text-xs text-slate-500 bg-slate-800 px-2 py-1 rounded ml-2">AI ENHANCED</span></h1>
            <p class="text-slate-400 text-sm">Exec Intelligence & Risk Management</p>
        </div>
        <div class="flex items-center gap-6">
            <button onclick="updateDashboard(true)" class="p-2 bg-slate-800 rounded-full hover:bg-slate-700 transition" title="Force Refresh">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 text-cyan-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" /></svg>
            </button>
            <div class="text-right">
                <div class="text-4xl font-mono text-white" id="spot-price">--</div>
                <div class="flex items-center justify-end gap-2 has-tooltip relative cursor-help">
                    <span class="stat-label">Nifty Spot</span>
                    <span id="rsi-badge" class="text-xs px-2 py-0.5 rounded font-bold bg-slate-700 text-slate-400">RSI --</span>
                </div>
            </div>
        </div>
    </div>
    <!-- SYSTEM STATUS PANEL (NEW - REQUIRED FOR POSITIONS) -->
    <div class="glass-panel p-3 rounded-xl border-l-4 border-cyan-500 mb-4 bg-slate-800/50">
        <div class="flex justify-between items-center flex-wrap gap-4">
            <div class="flex items-center gap-4">
                <div>
                    <div class="stat-label text-cyan-300">Backend Status</div>
                    <div class="flex items-center gap-3 mt-1">
                        <div class="flex items-center">
                            <span class="live-dot bg-gray-500" id="python-status"></span>
                            <span class="text-xs text-slate-300">Python</span>
                        </div>
                        <div class="flex items-center">
                            <span class="live-dot bg-gray-500" id="go-status"></span>
                            <span class="text-xs text-slate-300">Go</span>
                        </div>
                    </div>
                </div>
                <div class="h-8 w-px bg-slate-700"></div>
                <div>
                    <div class="stat-label text-cyan-300">Active Backend</div>
                    <div class="text-white font-bold" id="active-backend">--</div>
                </div>
                <div class="h-8 w-px bg-slate-700"></div>
                <div>
                    <div class="stat-label text-cyan-300">Position Source</div>
                    <div class="text-white font-mono text-sm" id="position-source">--</div>
                </div>
            </div>
            <div class="flex gap-2">
                <span class="backend-badge bg-slate-700 text-slate-400" id="feature-execution">Execution ✗</span>
                <span class="backend-badge bg-slate-700 text-slate-400" id="feature-management">Position Mgmt ✗</span>
            </div>
        </div>
    </div>
    <!-- MARKET INTEL PANEL (NEW) -->
    <div class="glass-panel p-3 rounded-xl border-l-4 border-indigo-500 mb-6 bg-slate-800/50">
        <div class="flex justify-between items-center flex-wrap gap-4">
            <div class="flex items-center gap-4">
                <div>
                    <div class="stat-label text-indigo-300">Market Regime</div>
                    <div class="font-bold text-white flex items-center" id="regime-val">--</div>
                </div>
                <div class="h-8 w-px bg-slate-700"></div>
                <div>
                    <div class="stat-label text-indigo-300">IV Rank</div>
                    <div class="font-bold text-white" id="iv-rank-val">--</div>
                </div>
                <div class="h-8 w-px bg-slate-700"></div>
                <div>
                    <div class="stat-label text-indigo-300">Strategic Bias</div>
                    <div class="text-xs text-slate-300 max-w-xs" id="strategy-msg">Initializing...</div>
                </div>
            </div>
            <div class="text-right">
                <div class="stat-label text-indigo-300">DTE Signal</div>
                <div class="text-xs font-mono text-yellow-400" id="dte-signal">--</div>
            </div>
        </div>
    </div>

    <!-- GREEKS RADAR -->
    <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <div class="glass-panel p-4 rounded-xl border-t-2 border-orange-500">
            <div class="stat-label">Gamma Risk (ATM)</div>
            <div class="text-2xl font-bold text-orange-400 mt-1" id="greek-gamma">--</div>
            <div class="text-[10px] text-slate-400 mt-1" id="gamma-msg">Checking...</div>
        </div>
        <div class="glass-panel p-4 rounded-xl border-t-2 border-green-500">
            <div class="stat-label">Theta Decay (Daily)</div>
            <div class="text-2xl font-bold text-green-400 mt-1" id="greek-theta">--</div>
            <div class="text-[10px] text-slate-400 mt-1">Time Value edge</div>
        </div>
        <div class="glass-panel p-4 rounded-xl border-t-2 border-purple-500">
            <div class="stat-label">Volatility Skew</div>
            <div class="text-2xl font-bold text-purple-400 mt-1" id="skew-val">--</div>
            <div class="text-[10px] text-slate-400 mt-1" id="skew-msg">Put vs Call Bias</div>
        </div>
        <div class="glass-panel p-4 rounded-xl border-t-2 border-blue-500">
            <div class="stat-label">India VIX</div>
            <div class="text-2xl font-bold text-blue-400 mt-1" id="vix-val">--</div>
            <div class="text-[10px] text-slate-400 mt-1" id="vix-change">--</div>
        </div>
    </div>

    <!-- STRANGLE SECTION -->
    <div class="flex justify-between items-center mb-3 px-1">
        <h2 class="text-slate-400 text-xs font-bold uppercase tracking-widest">Smart Strangle Setup (Regime Adjusted)</h2>
        
        <!-- RISK PROFILE TOGGLE -->
        <div class="bg-slate-800 p-1 rounded-lg flex">
            <input type="radio" name="profile" id="prof-cons" class="hidden profile-radio" value="conservative" onclick="setProfile('conservative')">
            <label for="prof-cons" class="px-3 py-1 text-xs rounded cursor-pointer text-slate-400 hover:text-white transition">Conservative</label>
            <input type="radio" name="profile" id="prof-mod" class="hidden profile-radio" value="moderate" onclick="setProfile('moderate')" checked>
            <label for="prof-mod" class="px-3 py-1 text-xs rounded cursor-pointer text-slate-400 hover:text-white transition">Moderate</label>
            <input type="radio" name="profile" id="prof-agg" class="hidden profile-radio" value="aggressive" onclick="setProfile('aggressive')">
            <label for="prof-agg" class="px-3 py-1 text-xs rounded cursor-pointer text-slate-400 hover:text-white transition">Aggressive</label>
        </div>
    </div>
    
    <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">
        <!-- Calls -->
        <div class="glass-panel p-6 rounded-2xl border-t-4 border-red-500 relative">
            <div class="flex justify-between items-start">
                <div><div class="stat-label">Rec. Short Call</div><div class="text-3xl font-bold text-white" id="rec-call">--</div></div>
                <div class="text-right"><div class="text-[14px] text-slate-400"> Δ <span class="text-white" id="call-delta">--</span></div><div class="text-[14px] text-slate-400">θ <span class="text-green-400" id="call-theta">--</span></div></div>
            </div>
            <div class="mt-3 border-t border-slate-700 pt-2">
                <div class="flex justify-between text-[14px] text-slate-400 mb-1"><span>Order Flow</span><span id="liq-call-msg">Checking...</span></div>
                <div class="flow-bar"><div id="flow-call-buy" class="flow-buy" style="width: 50%"></div><div id="flow-call-sell" class="flow-sell" style="width: 50%"></div></div>
            </div>
        </div>

        <!-- Center (Execution Hub) -->
        <div class="glass-panel p-6 rounded-2xl border-t-4 border-blue-500 text-center relative">
            <div class="stat-label mb-2">Strangle Credit</div>
            <div class="text-4xl font-bold text-blue-400 mb-1" id="est-credit">--</div>
            <div class="text-xs font-mono text-slate-400 mb-3" id="strangle-pnl">P&L: --</div>
            
            <!-- EXECUTE BUTTON -->
            <button onclick="executeStrangle()" class="w-full py-2 bg-red-600 hover:bg-red-700 text-white font-bold rounded-lg text-sm transition-all mb-4 shadow-lg shadow-red-900/50 active:scale-95">
                EXECUTE (1 Lot)
            </button>

            <div class="grid grid-cols-2 gap-2 text-left bg-slate-800 p-3 rounded-lg">
                <div><div class="stat-label">Max Pain</div><div class="text-white font-mono text-lg" id="max-pain">--</div></div>
                <div class="has-tooltip relative cursor-help">
                    <div class="stat-label">PCR</div>
                    <div class="text-white font-mono text-lg" id="pcr-val">--</div>
                    <div class="tooltip"><strong class="block text-white mb-1">PCR Decoder</strong><ul class="list-disc pl-3 space-y-1 text-slate-300"><li><span class="text-green-400">> 1.2:</span> Bullish</li><li><span class="text-yellow-400">0.8-1.2:</span> Neutral</li><li><span class="text-red-400">< 0.8:</span> Bearish</li></ul></div>
                </div>
            </div>
        </div>

        <!-- Puts -->
        <div class="glass-panel p-6 rounded-2xl border-t-4 border-green-500 relative">
            <div class="flex justify-between items-start">
                <div><div class="stat-label">Rec. Short Put</div><div class="text-3xl font-bold text-white" id="rec-put">--</div></div>
                <div class="text-right"><div class="text-[14px] text-slate-400">Δ  <span class="text-white" id="put-delta">--</span></div><div class="text-[14px] text-slate-400">θ <span class="text-green-400" id="put-theta">--</span></div></div>
            </div>
            <div class="mt-3 border-t border-slate-700 pt-2">
                <div class="flex justify-between text-[14px] text-slate-400 mb-1"><span>Order Flow</span><span id="liq-put-msg">Checking...</span></div>
                <div class="flow-bar"><div id="flow-put-buy" class="flow-buy" style="width: 50%"></div><div id="flow-put-sell" class="flow-sell" style="width: 50%"></div></div>
            </div>
        </div>
    </div>
    
    <!-- Chart Toggles -->
    <div class="flex justify-between items-center mb-2 px-1">
        <h3 class="text-slate-400 text-xs font-bold uppercase tracking-widest">Strangle Premium Monitor</h3>
        <div class="flex items-center">
            <span class="mr-2 text-xs text-slate-400">Show Chart</span>
            <div class="relative inline-block w-10 h-6 align-middle select-none transition duration-200 ease-in">
                <input type="checkbox" name="toggleStrangle" id="strangle-chart-toggle" class="toggle-checkbox absolute block w-6 h-6 rounded-full bg-white border-4 appearance-none cursor-pointer" onclick="toggleStrangleChart()" />
                <label for="strangle-chart-toggle" class="toggle-label block overflow-hidden h-6 rounded-full bg-gray-600 cursor-pointer"></label>
            </div>
        </div>
    </div>
    <div id="strangle-premium-chart-container" class="glass-panel p-4 rounded-xl mb-8 hidden">
         <div class="flex justify-between text-xs mb-2"><span class="text-slate-500">Combined Premium Decay</span><div class="flex gap-4"><span class="text-green-400"> Decay (Profit)</span><span class="text-red-400"> Spike (Loss)</span></div></div>
         <div class="relative h-48 w-full"><canvas id="strangleChart"></canvas></div>
    </div>

   <!-- LIVE POSITIONS TABLE (SCROLLABLE) -->
    <div class="glass-panel rounded-xl overflow-hidden mb-6">
        <div class="flex justify-between items-center p-4 border-b border-slate-700">
            <h3 class="text-lg font-bold text-white flex items-center gap-2">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-cyan-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                </svg>
                Live Positions
            </h3>
            
            <div class="flex items-center gap-4">
                <!-- Close All Button -->
                <button onclick="closeAllPositions()" id="close-all-btn" class="px-4 py-2 bg-red-600 hover:bg-red-700 text-white text-sm font-bold rounded-lg transition shadow-lg hidden">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 inline mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                    Close All
                </button>
                
                <!-- Toggle Switch -->
                <div class="flex items-center gap-2">
                    <span class="text-xs text-slate-400">Show</span>
                    <div class="relative inline-block w-10 h-6 align-middle select-none transition duration-200 ease-in">
                        <input type="checkbox" name="togglePositions" id="positions-toggle" class="toggle-checkbox absolute block w-6 h-6 rounded-full bg-white border-4 appearance-none cursor-pointer" onclick="togglePositions()" checked />
                        <label for="positions-toggle" class="toggle-label block overflow-hidden h-6 rounded-full bg-gray-600 cursor-pointer"></label>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Scrollable Container -->
        <div id="positions-container" class="positions-scroll-container">
            <table class="w-full text-sm">
                <thead class="text-xs text-slate-300 uppercase bg-slate-700 sticky top-0 z-10">
                    <tr>
                        <th class="px-4 py-3 text-left">Symbol</th>
                        <th class="px-4 py-3 text-right">Qty</th>
                        <th class="px-4 py-3 text-right">Avg Price</th>
                        <th class="px-4 py-3 text-right">LTP</th>
                        <th class="px-4 py-3 text-right">P&L</th>
                        <th class="px-4 py-3 text-right">Action</th>
                    </tr>
                </thead>
                <tbody id="positions-body">
                    <tr><td colspan="6" class="px-4 py-3 text-center text-slate-500">Loading positions...</td></tr>
                </tbody>
            </table>
        </div>
        
        <!-- Footer with Total MTM (Always Visible) -->
        <div class="bg-slate-800/50 border-t border-slate-700 p-3">
            <div class="flex justify-between items-center">
                <span class="text-sm text-slate-400 font-semibold">Total MTM:</span>
                <span class="text-lg font-bold" id="total-mtm">--</span>
            </div>
        </div>
    </div>

    <!-- STRADDLE SECTION -->
    <div class="flex justify-between items-center mb-2 px-1">
        <h2 class="text-slate-400 text-xs font-bold uppercase tracking-widest">ATM Straddle Monitor</h2>
        <div class="flex items-center">
            <span class="mr-2 text-xs text-slate-400">Show Chart</span>
            <div class="relative inline-block w-10 h-6 align-middle select-none transition duration-200 ease-in">
                <input type="checkbox" name="toggle" id="chart-toggle" class="toggle-checkbox absolute block w-6 h-6 rounded-full bg-white border-4 appearance-none cursor-pointer" onclick="toggleStraddleChart()" />
                <label for="chart-toggle" class="toggle-label block overflow-hidden h-6 rounded-full bg-gray-600 cursor-pointer"></label>
            </div>
        </div>
    </div>

    <div class="glass-panel p-6 rounded-2xl border border-indigo-500/30 mb-6 bg-gradient-to-r from-slate-900 to-indigo-900/20">
        <div class="grid grid-cols-1 md:grid-cols-4 gap-6 items-center">
            <div><div class="stat-label text-indigo-300">ATM Strike</div><div class="text-3xl font-bold text-white" id="straddle-atm">--</div></div>
            <div><div class="stat-label text-indigo-300">Straddle Premium</div><div class="text-3xl font-bold text-indigo-400" id="straddle-cost">--</div><div class="text-xs mt-1 font-mono" id="straddle-pnl">P&L: --</div></div>
            <div class="col-span-2"><div class="stat-label text-indigo-300 mb-1">Breakeven Range</div><div class="flex items-center space-x-2"><span class="text-xl font-mono text-green-400" id="straddle-lower">--</span><span class="text-slate-500">⟷</span><span class="text-xl font-mono text-red-400" id="straddle-upper">--</span></div></div>
        </div>
        <div id="premium-chart-container" class="mt-6 pt-6 border-t border-slate-700 hidden">
             <div class="flex justify-between text-xs mb-2"><span class="text-green-400">Decay Zone (Profit)</span><span class="text-red-400">▲ Spike Zone (Loss)</span></div>
             <div class="relative h-64 w-full"><canvas id="straddleChart"></canvas></div>
        </div>
    </div>

    <!-- Main OI Chart -->
    <div class="glass-panel p-4 rounded-xl mb-6">
        <h3 class="text-lg font-semibold text-slate-200 mb-4">OI Structure (Bars) & Volume (Lines)</h3>
        <div class="relative h-96 w-full"><canvas id="oiChart"></canvas></div>
    </div>

    <!-- HISTORICAL PROBABILITIES -->
    <div class="mb-8">
        <div class="flex justify-between items-center mb-4">
            <h2 class="text-slate-400 text-xs font-bold uppercase tracking-widest">Historical Probabilities</h2>
            <button onclick="saveDailyData()" class="text-xs bg-blue-600 hover:bg-blue-700 text-white px-3 py-1 rounded transition" id="save-btn">Save Today's Data (EOD)</button>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div class="glass-panel p-4 rounded-xl border-l-4 border-green-500">
                <div class="flex justify-between"><span class="text-green-400 font-bold text-xs">CONSERVATIVE</span></div>
                <div class="flex justify-between text-sm mt-2"><span class="text-slate-400">CE</span><span class="font-mono text-white" id="hist-call-cons">--</span></div>
                <div class="flex justify-between text-sm"><span class="text-slate-400">PE</span><span class="font-mono text-white" id="hist-put-cons">--</span></div>
            </div>
            <div class="glass-panel p-4 rounded-xl border-l-4 border-yellow-500">
                <div class="flex justify-between"><span class="text-yellow-400 font-bold text-xs">MODERATE</span></div>
                <div class="flex justify-between text-sm mt-2"><span class="text-slate-400">CE</span><span class="font-mono text-white" id="hist-call-mod">--</span></div>
                <div class="flex justify-between text-sm"><span class="text-slate-400">PE</span><span class="font-mono text-white" id="hist-put-mod">--</span></div>
            </div>
            <div class="glass-panel p-4 rounded-xl border-l-4 border-red-500">
                <div class="flex justify-between"><span class="text-red-400 font-bold text-xs">AGGRESSIVE</span></div>
                <div class="flex justify-between text-sm mt-2"><span class="text-slate-400">CE</span><span class="font-mono text-white" id="hist-call-agg">--</span></div>
                <div class="flex justify-between text-sm"><span class="text-slate-400">PE</span><span class="font-mono text-white" id="hist-put-agg">--</span></div>
            </div>
        </div>
        <div class="text-center mt-2 text-[10px] text-slate-500" id="hist-context">Loading DB...</div>
    </div>

    <script>
        const TEST_MODE = true; 
        let oiChart, straddleChart, strangleChart;
        let straddleHistory = { labels: [], data: [] }; 
        let strangleHistory = { labels: [], data: [] };
        let initialStraddlePremium = null;
        let initialStranglePremium = null;
        
        // CURRENT SELECTED PROFILE
        let currentProfile = 'moderate'; 
        let globalData = null;

        function setProfile(prof) {
            currentProfile = prof;
            if (globalData) renderStrangleData(globalData);
        }

        function initCharts() {
            // OI Chart
            const ctxOI = document.getElementById('oiChart').getContext('2d'); 
            oiChart = new Chart(ctxOI, { 
                type: 'bar', 
                data: { labels: [], datasets: [ 
                    { label: 'Call OI', data: [], backgroundColor: 'rgba(239, 68, 68, 0.7)', order: 2, yAxisID: 'y' }, 
                    { label: 'Put OI', data: [], backgroundColor: 'rgba(34, 197, 94, 0.7)', order: 3, yAxisID: 'y' }, 
                    { type: 'line', label: 'Call Vol', data: [], borderColor: '#f87171', backgroundColor: 'rgba(248, 113, 113, 0.1)', borderWidth: 2, pointRadius: 0, fill: true, tension: 0.4, yAxisID: 'y1', order: 0 }, 
                    { type: 'line', label: 'Put Vol', data: [], borderColor: '#4ade80', backgroundColor: 'rgba(74, 222, 128, 0.1)', borderWidth: 2, pointRadius: 0, fill: true, tension: 0.4, yAxisID: 'y1', order: 1 } 
                ]}, 
                options: { responsive: true, maintainAspectRatio: false, scales: { x: { display: true, grid: { display: false } }, y: { display: true, position: 'left', grid: {color:'rgba(255,255,255,0.05)'} }, y1: { display: true, position: 'right', grid: {display:false}, ticks:{display:false} } } } 
            });

            const ctxStraddle = document.getElementById('straddleChart').getContext('2d');
            straddleChart = new Chart(ctxStraddle, { type: 'line', data: { labels: [], datasets: [{ label: 'Premium', data: [], borderColor: '#818cf8', backgroundColor: 'rgba(129, 140, 248, 0.1)', fill: true, tension: 0.4 }] }, options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { display: false }, y: { display: true, grid: { color: 'rgba(255,255,255,0.05)' } } } } });

            const ctxStrangle = document.getElementById('strangleChart').getContext('2d');
            strangleChart = new Chart(ctxStrangle, { type: 'line', data: { labels: [], datasets: [{ label: 'Premium', data: [], borderColor: '#38bdf8', backgroundColor: 'rgba(56, 189, 248, 0.1)', fill: true, tension: 0.4 }] }, options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { display: false }, y: { display: true, grid: { color: 'rgba(255,255,255,0.05)' } } } } });
        }

        function toggleStraddleChart() { const c = document.getElementById('premium-chart-container'); const cb = document.getElementById('chart-toggle'); cb.checked ? c.classList.remove('hidden') : c.classList.add('hidden'); }
        function toggleStrangleChart() { const c = document.getElementById('strangle-premium-chart-container'); const cb = document.getElementById('strangle-chart-toggle'); cb.checked ? c.classList.remove('hidden') : c.classList.add('hidden'); }
        
        function togglePositions() {
            const container = document.getElementById('positions-container');
            const cb = document.getElementById('positions-toggle');
            if(cb.checked) {
                container.style.maxHeight = '500px'; 
                container.style.opacity = '1';
                container.classList.remove('hidden');
            } else {
                container.style.maxHeight = '0px';
                container.style.opacity = '0';
                setTimeout(() => container.classList.add('hidden'), 300); // Wait for transition
            }
        }

        async function saveDailyData() {
            const btn = document.getElementById('save-btn'); btn.innerText = "Saving...";
            try { await fetch('/api/update_daily', { method: 'POST' }); btn.innerText = "Saved "; setTimeout(() => btn.innerText = "Save Today's Data (EOD)", 2000); } 
            catch(e) { alert("Error saving data"); btn.innerText = "Error "; }
        }

        async function fetchHistory() {
            try {
                const res = await fetch('/api/history');
                const data = await res.json();
                if(!data || !data.stats) return;

                document.getElementById('hist-context').innerText = \`Analyzed \${data.sample_size} historical days matching current DTE. Source: \${data.source}\`;
                
                ['cons', 'mod', 'agg'].forEach(type => {
                    let key = type === 'cons' ? 'conservative' : type === 'mod' ? 'moderate' : 'aggressive';
                    document.getElementById(\`hist-call-\${type}\`).innerText = data.suggestions[key].call;
                    document.getElementById(\`hist-put-\${type}\`).innerText = data.suggestions[key].put;
                });

                // RSI BADGE LOGIC
                const rsiEl = document.getElementById('rsi-badge');
                if(data.rsi) {
                    rsiEl.innerText = "RSI " + data.rsi;
                    if(data.rsi > 70) { rsiEl.className = "text-xs px-2 py-0.5 rounded font-bold bg-red-900 text-red-300 cursor-help"; }
                    else if(data.rsi < 30) { rsiEl.className = "text-xs px-2 py-0.5 rounded font-bold bg-green-900 text-green-300 cursor-help"; }
                    else { rsiEl.className = "text-xs px-2 py-0.5 rounded font-bold bg-slate-700 text-slate-300 cursor-help"; }
                }
            } catch(e) { console.error("History fetch error", e); }
        }

        function renderStrangleData(data) {
            const intel = data.strangle_intel[currentProfile];
            if (!intel) return;

            document.getElementById('rec-call').innerText = intel.rec_call ?? '--';
            document.getElementById('rec-put').innerText = intel.rec_put ?? '--';
            document.getElementById('est-credit').innerText = "" + (intel.est_credit?.toFixed(2) ?? '--');
            
            document.getElementById('call-delta').innerText = intel.call_greeks?.delta ?? '--';
            document.getElementById('call-theta').innerText = intel.call_greeks?.theta ?? '--';
            document.getElementById('put-delta').innerText = intel.put_greeks?.delta ?? '--';
            document.getElementById('put-theta').innerText = intel.put_greeks?.theta ?? '--';

            const liqCall = intel.call_stats?.ok;
            document.getElementById('liq-call-msg').innerText = liqCall ? "Liquid" : "Low Vol";
            
            const liqPut = intel.put_stats?.ok;
            document.getElementById('liq-put-msg').innerText = liqPut ? "Liquid" : "Low Vol";

            const totalCall = (intel.call_stats?.buy_qty || 0) + (intel.call_stats?.sell_qty || 0);
            if(totalCall > 0) {
                const buyPct = (intel.call_stats.buy_qty / totalCall) * 100;
                document.getElementById('flow-call-buy').style.width = buyPct + "%";
                document.getElementById('flow-call-sell').style.width = (100 - buyPct) + "%";
            }
            const totalPut = (intel.put_stats?.buy_qty || 0) + (intel.put_stats?.sell_qty || 0);
            if(totalPut > 0) {
                const buyPct = (intel.put_stats.buy_qty / totalPut) * 100;
                document.getElementById('flow-put-buy').style.width = buyPct + "%";
                document.getElementById('flow-put-sell').style.width = (100 - buyPct) + "%";
            }
            
            const currentCost = intel.est_credit;
            if(initialStranglePremium === null) initialStranglePremium = currentCost;
            const stDiff = initialStranglePremium - currentCost;
            const stPnl = stDiff * 75; // Changed to 75 as per user request (1 Lot)
            const stPnlEl = document.getElementById('strangle-pnl');
            stPnlEl.innerText = (stPnl >= 0 ? "+" : "") + "" + stPnl.toFixed(0);
            stPnlEl.className = stPnl >= 0 ? "text-xs font-mono mb-3 text-green-400 font-bold" : "text-xs font-mono mb-3 text-red-400 font-bold";
            
            return currentCost;
        }

           // Execute Strangle with Go API
        async function executeStrangle() {
            if (!globalData || !globalData.strangle_intel) return;
            
            const intel = globalData.strangle_intel[currentProfile];
            
            if (!confirm(\`EXECUTE STRANGLE via GO API?\\n\\nCall: \${intel.rec_call}\\nPut: \${intel.rec_put}\\nQty: 75\\n\\n✅ Auto Risk Management: ENABLED\\n\\nProceed?\`)) return;
            
            try {
                const res = await fetch('/execute_strangle', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        call_strike: intel.rec_call,
                        put_strike: intel.rec_put,
                        qty: 75,
                        autoTrade: true  // ✅ Enable Go's auto-management
                    })
                });
                
                const result = await res.json();
                
                if(result.status === 'success') {
                    alert(\`✅ Order Executed Successfully!\\n\\nCall: \${result.execution_details.call_symbol} @ \${result.execution_details.call_entry}\\nPut: \${result.execution_details.put_symbol} @ \${result.execution_details.put_entry}\\n\\nTotal Credit: \${result.execution_details.total_credit}\\n\\n🤖 Auto Management: ACTIVE\`);
                } else {
                    alert('❌ Error: ' + result.message);
                }
            } catch(e) {
                alert('❌ Network Error: ' + e.message);
            }
        }

         // Check system status on load
        let systemStatus = null;
        let positionSource = 'unknown';

        // Check system status on load
        async function checkSystemStatus() {
            try {
                const res = await fetch('/api/system_status');
                systemStatus = await res.json();
                
                console.log('📊 System Status:', systemStatus);
                
                // Update status indicators
                document.getElementById('python-status').className = 
                    'live-dot ' + (systemStatus.python.available ? 'bg-green-500' : 'bg-red-500');
                document.getElementById('go-status').className = 
                    'live-dot ' + (systemStatus.go.available ? 'bg-green-500' : 'bg-red-500');
                
                // Update active backend
                document.getElementById('active-backend').innerText = 
                    systemStatus.activeBackend.toUpperCase() + ' API';
                
                // Update feature badges
                document.getElementById('feature-execution').className = 
                    'backend-badge ' + (systemStatus.go.available ? 'bg-green-900 text-green-300' : 'bg-slate-700 text-slate-400');
                document.getElementById('feature-execution').innerText = 
                    'Execution ' + (systemStatus.go.available ? '✓' : '✗');
                
                if (systemStatus.features.positionManagement && systemStatus.go.available) {
                    document.getElementById('feature-management').className = 
                        'backend-badge bg-green-900 text-green-300';
                    document.getElementById('feature-management').innerText = 'Position Mgmt ✓';
                    
                    // Show close buttons if Go API is available
                    document.getElementById('close-all-btn').classList.remove('hidden');
                }
                
            } catch (error) {
                console.error('❌ System status check failed:', error);
            }
        }

        async function updatePositions() {
            try {
                console.log('🔄 Fetching positions...');
                const res = await fetch('/positions');
                const json = await res.json();
                
                console.log('📦 Positions response:', json);
                
                const positions = json.data || [];
                positionSource = json.source || 'unknown';
                
                // Update source indicator
                document.getElementById('position-source').innerText = positionSource.toUpperCase();
                
                const tbody = document.getElementById('positions-body');
                tbody.innerHTML = '';
                let totalMtm = 0;

                if (positions.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="6" class="px-4 py-3 text-center text-slate-500">No positions</td></tr>';
                } else {
                    // Separate open and closed positions
                    const openPos = positions.filter(p => p.status === 'OPEN');
                    const closedPos = positions.filter(p => p.status === 'CLOSED');
                    
                    // Check if position management is available
                    const canClose = systemStatus && systemStatus.features && systemStatus.features.positionManagement;
                    
                    // Render OPEN positions first
                    openPos.forEach(pos => {
                        const mtm = pos.mtm || ((pos.last_price - pos.average_price) * pos.quantity);
                        totalMtm += mtm;
                        
                        // Always show close button, but disable if not supported
                        const closeBtn = \`
                            <button 
                                onclick="closePosition('\${pos.tradingsymbol}', \${Math.abs(pos.quantity)})" 
                                class="px-3 py-1 \${canClose ? 'bg-red-600 hover:bg-red-700' : 'bg-gray-600 cursor-not-allowed'} text-white text-xs rounded transition font-semibold"
                                \${canClose ? '' : 'disabled'}
                            >
                                Close
                            </button>
                        \`;
                        
                        tbody.innerHTML += \`
                            <tr class="border-b border-slate-800 hover:bg-slate-800/30 transition">
                                <td class="px-4 py-3 text-white font-medium">\${pos.tradingsymbol}</td>
                                <td class="px-4 py-3 text-right text-slate-300">\${pos.quantity}</td>
                                <td class="px-4 py-3 text-right text-slate-300">\${pos.average_price.toFixed(2)}</td>
                                <td class="px-4 py-3 text-right text-white">\${pos.last_price.toFixed(2)}</td>
                                <td class="px-4 py-3 text-right font-bold \${mtm >= 0 ? 'text-green-400' : 'text-red-400'}">\${mtm.toFixed(2)}</td>
                                <td class="px-4 py-3 text-right">\${closeBtn}</td>
                            </tr>
                        \`;
                    });
                    
                    // Add separator if there are closed positions
                    if (closedPos.length > 0 && openPos.length > 0) {
                        tbody.innerHTML += \`
                            <tr class="bg-slate-800/50">
                                <td colspan="6" class="px-4 py-2 text-center text-slate-400 text-xs font-bold uppercase tracking-wider">
                                    ─── Closed Positions (Today) ───
                                </td>
                            </tr>
                        \`;
                    }
                    
                    // Render CLOSED positions
                    closedPos.forEach(pos => {
                        totalMtm += pos.mtm;
                        tbody.innerHTML += \`
                            <tr class="border-b border-slate-800 bg-slate-900/30 opacity-70">
                                <td class="px-4 py-3 text-slate-400 font-medium">\${pos.tradingsymbol}</td>
                                <td class="px-4 py-3 text-right text-slate-500">\${pos.quantity}</td>
                                <td class="px-4 py-3 text-right text-slate-500">\${pos.average_price.toFixed(2)}</td>
                                <td class="px-4 py-3 text-right text-slate-400">\${pos.exit_price.toFixed(2)}</td>
                                <td class="px-4 py-3 text-right font-bold \${pos.mtm >= 0 ? 'text-green-400' : 'text-red-400'}">\${pos.mtm.toFixed(2)}</td>
                                <td class="px-4 py-3 text-right text-xs text-slate-500">Closed \${pos.closed_at || ''}</td>
                            </tr>
                        \`;
                    });
            }
            
            const totalEl = document.getElementById('total-mtm');
            totalEl.innerText = totalMtm.toFixed(2);
            totalEl.className = \`text-lg font-bold \${totalMtm >= 0 ? 'text-green-400' : 'text-red-400'}\`;

            // Show breakdown if available
            if (json.breakdown) {
                console.log(\`📊 MTM Breakdown: Open: \${json.breakdown.open_mtm} | Closed: \${json.breakdown.closed_mtm} | Total: \${totalMtm.toFixed(2)}\`);
            }
            
        } catch (error) {
            console.error('❌ Positions fetch failed:', error);
            document.getElementById('positions-body').innerHTML = 
                '<tr><td colspan="6" class="px-4 py-3 text-center text-red-400">Failed to load positions</td></tr>';
        }
    }

        async function closePosition(symbol, qty) {
            if (!confirm(\`Close position \${symbol}?\`)) return;
            
            try {
                const res = await fetch('/close_position', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ tradingSymbol: symbol, quantity: qty })
                });
                const result = await res.json();
                
                if (result.success) {
                    alert('✅ Position closed');
                    updatePositions();
                } else {
                    alert('❌ ' + result.message);
                }
            } catch (error) {
                alert('❌ Failed to close position: ' + error.message);
            }
        }

        async function closeAllPositions() {
            if (!confirm('Close ALL positions?')) return;
            
            try {
                const res = await fetch('/close_all_positions', { method: 'POST' });
                const result = await res.json();
                
                if (result.success) {
                    alert('✅ ' + result.message);
                    updatePositions();
                } else {
                    alert('❌ ' + result.message);
                }
            } catch (error) {
                alert('❌ Failed to close positions: ' + error.message);
            }
        }


         // Initialize
        console.log('🚀 Dashboard initializing...');
        checkSystemStatus();
        updatePositions();
        setInterval(checkSystemStatus, 30000); // Check status every 30s
        setInterval(updatePositions, 2000); // Update positions every 2s

        async function updateDashboard(manualRefresh = false) {
            try {
                if(manualRefresh) document.querySelector('button').classList.add('animate-spin');
                const res = await fetch('/api/data');
                const data = await res.json();
                if(manualRefresh) document.querySelector('button').classList.remove('animate-spin');
                if(!data || !data.metrics) return;
                
                globalData = data; 

                // OI CHART
                if (oiChart && data.chart_data) {
                    oiChart.data.labels = data.chart_data.strikes;
                    oiChart.data.datasets[0].data = data.chart_data.ce_oi;
                    oiChart.data.datasets[1].data = data.chart_data.pe_oi;
                    oiChart.data.datasets[2].data = data.chart_data.ce_vol;
                    oiChart.data.datasets[3].data = data.chart_data.pe_vol;
                    oiChart.update('none');
                }
                
                // NEW: Render Market Intel
                if(data.market_intel) {
                    const regimeEl = document.getElementById('regime-val');
                    const r = data.market_intel.regime;
                    
                    let rColor = "text-white";
                    if(r.includes("Bullish")) rColor = "text-green-400";
                    else if(r.includes("Bearish")) rColor = "text-red-400";
                    else if(r.includes("Volatile")) rColor = "text-orange-400";
                    
                    regimeEl.innerHTML = \`<span class="live-dot bg-green-500"></span><span class="\${rColor}">\${r}</span>\`;
                    
                    const ivEl = document.getElementById('iv-rank-val');
                    ivEl.innerText = data.market_intel.iv_rank + " (" + data.market_intel.iv_status.split(' ')[0] + ")";
                    
                    document.getElementById('strategy-msg').innerText = data.market_intel.regime_bias + " Bias | " + data.market_intel.dte_msg;
                    document.getElementById('dte-signal').innerText = data.market_intel.dte_msg.includes("Standard") ? "Standard" : "Risk Alert";
                    
                    // Update RSI badge from Live Data
                    const rsiEl = document.getElementById('rsi-badge');
                    rsiEl.innerText = "RSI " + data.market_intel.rsi;
                    if(data.market_intel.rsi > 70) rsiEl.className = "text-xs px-2 py-0.5 rounded font-bold bg-red-900 text-red-300";
                    else if(data.market_intel.rsi < 30) rsiEl.className = "text-xs px-2 py-0.5 rounded font-bold bg-green-900 text-green-300";
                    else rsiEl.className = "text-xs px-2 py-0.5 rounded font-bold bg-slate-700 text-slate-300";
                }

                document.getElementById('spot-price').innerText = data.nifty_spot?.toFixed(2) ?? '--';
                document.getElementById('max-pain').innerText = data.metrics?.max_pain ?? '--';
                document.getElementById('pcr-val').innerText = data.metrics?.pcr ?? '--';
                document.getElementById('straddle-cost').innerText = "" + (data.straddle_intel?.cost?.toFixed(2) ?? '--');
                document.getElementById('straddle-atm').innerText = data.straddle_intel?.atm_strike ?? '--';
                document.getElementById('straddle-lower').innerText = data.straddle_intel?.lower_be?.toFixed(0) ?? '--';
                document.getElementById('straddle-upper').innerText = data.straddle_intel?.upper_be?.toFixed(0) ?? '--';

                if(data.greeks) {
                    document.getElementById('greek-gamma').innerText = data.greeks.gamma;
                    document.getElementById('greek-theta').innerText = data.greeks.theta;
                    const gEl = document.getElementById('gamma-msg');
                    if(gEl) {
                        if(data.greeks.gamma > 0.002) { gEl.innerText = "High Risk"; gEl.className = "text-[10px] text-red-500 font-bold animate-pulse"; }
                        else { gEl.innerText = "Stable"; gEl.className = "text-[10px] text-slate-400"; }
                    }
                }
                if(data.skew) {
                    document.getElementById('skew-val').innerText = data.skew.value;
                    document.getElementById('skew-msg').innerText = data.skew.value > 1.2 ? "Bearish Bias" : (data.skew.value < 0.8 ? "Bullish Bias" : "Neutral");
                }
                if(data.vix) {
                    document.getElementById('vix-val').innerText = data.vix.value;
                    const chg = data.vix.change;
                    const vEl = document.getElementById('vix-change');
                    if(vEl) {
                        vEl.innerText = (chg>=0?"+":"") + chg.toFixed(2) + "%";
                        vEl.className = chg >= 0 ? "text-[10px] text-red-400" : "text-[10px] text-green-400";
                    }
                }

                if(data.strangle_intel) {
                    const currentStrangleCost = renderStrangleData(data);
                    
                    const istTimeStr = data.timestamp;
                    const [hh, mm] = istTimeStr.split(':').map(Number);
                    let isAfter930 = (hh > 9) || (hh === 9 && mm >= 30);
                    if (TEST_MODE) isAfter930 = true;

                    if (isAfter930 && currentStrangleCost) {
                        const straddleCost = data.straddle_intel.cost;
                        if(initialStraddlePremium === null) initialStraddlePremium = straddleCost;
                        const sDiff = initialStraddlePremium - straddleCost;
                        const sPnl = sDiff * 75; // Changed to 75 for Nifty PnL calc
                        const sPnlEl = document.getElementById('straddle-pnl');
                        sPnlEl.innerText = (sPnl >= 0 ? "+" : "") + "" + sPnl.toFixed(0);
                        sPnlEl.className = sPnl >= 0 ? "text-xs mt-1 font-mono text-green-400" : "text-xs mt-1 font-mono text-red-400";

                        const lastLabel = straddleHistory.labels[straddleHistory.labels.length - 1];
                        if (lastLabel !== istTimeStr.substring(0, 5)) {
                            strangleHistory.labels.push(istTimeStr.substring(0, 5));
                            strangleHistory.data.push(currentStrangleCost); 
                            straddleHistory.labels.push(istTimeStr.substring(0, 5));
                            straddleHistory.data.push(straddleCost);

                            // CHANGED: Increased buffer from 60 to 120 to show ~2 hours of data
                            if(strangleHistory.labels.length > 120) {
                                strangleHistory.labels.shift(); strangleHistory.data.shift();
                                straddleHistory.labels.shift(); straddleHistory.data.shift();
                            }

                            strangleChart.data.labels = strangleHistory.labels;
                            strangleChart.data.datasets[0].data = strangleHistory.data;
                            strangleChart.data.datasets[0].borderColor = currentStrangleCost < initialStranglePremium ? '#4ade80' : '#f87171';
                            strangleChart.update('none');

                            straddleChart.data.labels = straddleHistory.labels;
                            straddleChart.data.datasets[0].data = straddleHistory.data;
                            straddleChart.data.datasets[0].borderColor = straddleCost < initialStraddlePremium ? '#4ade80' : '#f87171';
                            straddleChart.update('none');
                        }
                    }
                }
                
                // Update Positions
                updatePositions();

            } catch (e) { console.error(e); }
        }

        initCharts();
        fetchHistory();
        toggleStraddleChart();
        toggleStrangleChart();
        togglePositions(); // Initialize toggle state
        setInterval(() => updateDashboard(false), 2000);
        console.log('🚀 Dashboard initializing with Go API...');
        checkSystemStatus();
        setInterval(checkSystemStatus, 30000); // Check status every 30s
    </script>
</body>
</html>
`;


app.get('/', (req, res) => res.send(getHtml()));

// ============================================
// START SERVER
// ============================================

app.listen(PORT, async () => {
    console.log(`
╔═══════════════════════════════════════════════════════════╗
║     NIFTY OPTIONS DASHBOARD - GO API INTEGRATION          ║
╠═══════════════════════════════════════════════════════════╣
║  Dashboard:      http://localhost:${PORT}                     ║
║  Python API:     ${BACKENDS.python.url}                  ║
║  Go API:         ${BACKENDS.go.url}                      ║
╠═══════════════════════════════════════════════════════════╣
║  Analytics:      Python (Best Intelligence)               ║
║  Execution:      Go API (Intelligent + Auto Mgmt)         ║
║  Positions:      Go API (Real-time Monitoring)            ║
╚═══════════════════════════════════════════════════════════╝
    `);

    // Check Go API availability on startup
    const goAvailable = await checkGoAPI();
    if (!goAvailable) {
        console.warn('⚠️  WARNING: Go API is not running!');
        console.warn('    Start it with: go run cmd/api/server.go');
    }
});