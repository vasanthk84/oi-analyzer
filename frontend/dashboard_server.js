const express = require('express');
const axios = require('axios');
const app = express();
const PORT = 3000;

app.use(express.json());

const getHtml = () => `
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Nifty Option Master</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { background-color: #0f172a; color: #e2e8f0; font-family: 'Inter', sans-serif; }
        .glass-panel { background: rgba(30, 41, 59, 0.7); backdrop-filter: blur(10px); border: 1px solid rgba(255,255,255,0.1); }
        .stat-label { font-size: 0.7rem; text-transform: uppercase; color: #94a3b8; letter-spacing: 0.05em; }
        .stat-val { font-size: 1.5rem; font-weight: 700; }
        .call-col { color: #f87171; }
        .put-col { color: #4ade80; }
        
        /* Toggle Switch */
        .toggle-checkbox:checked { right: 0; border-color: #68D391; }
        .toggle-checkbox:checked + .toggle-label { background-color: #68D391; }
        
        .zone-green { background: rgba(34, 197, 94, 0.1); border-left: 2px solid #22c55e; }
        .zone-red { background: rgba(239, 68, 68, 0.1); border-left: 2px solid #ef4444; }
    </style>
</head>
<body class="p-4 md:p-8 max-w-7xl mx-auto">

    <!-- Header -->
    <div class="flex justify-between items-center mb-6">
        <div>
            <h1 class="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-indigo-400 to-cyan-400">
                OPTION MASTER
            </h1>
            <p class="text-slate-400 text-sm">Strangle & Straddle Analysis (IST)</p>
        </div>
        <div class="flex items-center gap-4">
            <button onclick="updateDashboard(true)" class="p-2 bg-slate-800 rounded-full hover:bg-slate-700 transition" title="Force Refresh">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 text-cyan-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
            </button>
            <div class="text-right">
                <div class="text-4xl font-mono text-white" id="spot-price">--</div>
                <div class="stat-label">Nifty Spot</div>
            </div>
        </div>
    </div>

    <!-- STRANGLE SECTION -->
    <div class="flex justify-between items-center mb-2">
        <h2 class="text-slate-400 text-xs font-bold uppercase tracking-widest">Strangle (Range) Setup</h2>
         <!-- Toggle for Strangle Chart -->
        <div class="flex items-center">
            <span class="mr-2 text-xs text-slate-400">Show Premium Chart</span>
            <div class="relative inline-block w-10 h-6 align-middle select-none transition duration-200 ease-in">
                <input type="checkbox" name="toggleStrangle" id="strangle-chart-toggle" class="toggle-checkbox absolute block w-6 h-6 rounded-full bg-white border-4 appearance-none cursor-pointer" onclick="toggleStrangleChart()" checked/>
                <label for="strangle-chart-toggle" class="toggle-label block overflow-hidden h-6 rounded-full bg-gray-600 cursor-pointer"></label>
            </div>
        </div>
    </div>
    
    <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">
        <!-- Calls -->
        <div class="glass-panel p-6 rounded-2xl border-t-4 border-red-500 relative">
            <div class="stat-label">Resistance Wall</div>
            <div class="stat-val call-col mb-2" id="wall-res">--</div>
            <div class="border-t border-slate-700 my-3"></div>
            <div class="stat-label">Rec. Short Strike</div>
            <div class="text-2xl font-bold text-white" id="rec-call">--</div>
        </div>

        <!-- Center -->
        <div class="glass-panel p-6 rounded-2xl border-t-4 border-blue-500 text-center">
            <div class="stat-label mb-2">Strangle Credit</div>
            <div class="text-4xl font-bold text-blue-400 mb-1" id="est-credit">--</div>
            <div class="grid grid-cols-2 gap-2 text-left bg-slate-800 p-3 rounded-lg mt-4">
                <div>
                    <div class="stat-label">Max Pain</div>
                    <div class="text-white font-mono text-lg text-purple-400" id="max-pain">--</div>
                </div>
                <div>
                    <div class="stat-label">PCR Sentiment</div>
                    <div class="text-white font-mono text-lg" id="pcr-val">--</div>
                </div>
            </div>
        </div>

        <!-- Puts -->
        <div class="glass-panel p-6 rounded-2xl border-t-4 border-green-500 relative">
            <div class="stat-label">Support Wall</div>
            <div class="stat-val put-col mb-2" id="wall-supp">--</div>
            <div class="border-t border-slate-700 my-3"></div>
            <div class="stat-label">Rec. Short Strike</div>
            <div class="text-2xl font-bold text-white" id="rec-put">--</div>
        </div>
    </div>
    
    <!-- Strangle Premium Chart Container -->
    <div id="strangle-premium-chart-container" class="glass-panel p-4 rounded-xl mb-6">
         <div class="flex justify-between text-xs mb-2">
            <span class="text-slate-400 font-bold uppercase tracking-widest">Strangle Premium Decay (Rec. Strikes)</span>
            <div class="flex gap-4">
                <span class="text-green-400">▼ Decay (Profit)</span>
                <span class="text-red-400">▲ Spike (Loss)</span>
            </div>
         </div>
         <div class="relative h-48 w-full">
            <canvas id="strangleChart"></canvas>
         </div>
    </div>

    <!-- STRADDLE SECTION -->
    <div id="straddle-container" class="opacity-50 grayscale transition-all duration-500 pointer-events-none">
        <div class="flex justify-between items-center mb-2">
            <h2 class="text-slate-400 text-xs font-bold uppercase tracking-widest">
                ATM Straddle (Stability) Monitor <span id="time-status" class="ml-2 text-xs text-yellow-500"></span>
            </h2>
            
            <!-- Toggle for Chart -->
            <div class="flex items-center">
                <span class="mr-2 text-xs text-slate-400">Show Decay Chart</span>
                <div class="relative inline-block w-10 h-6 align-middle select-none transition duration-200 ease-in">
                    <input type="checkbox" name="toggle" id="chart-toggle" class="toggle-checkbox absolute block w-6 h-6 rounded-full bg-white border-4 appearance-none cursor-pointer" onclick="toggleStraddleChart()" checked/>
                    <label for="chart-toggle" class="toggle-label block overflow-hidden h-6 rounded-full bg-gray-600 cursor-pointer"></label>
                </div>
            </div>
        </div>

        <div class="glass-panel p-6 rounded-2xl border border-indigo-500/30 mb-6 bg-gradient-to-r from-slate-900 to-indigo-900/20">
            <div class="grid grid-cols-1 md:grid-cols-4 gap-6 items-center">
                <!-- ATM Strike -->
                <div>
                    <div class="stat-label text-indigo-300">ATM Strike</div>
                    <div class="text-3xl font-bold text-white" id="straddle-atm">--</div>
                </div>
                <!-- Cost -->
                <div>
                    <div class="stat-label text-indigo-300">Straddle Premium</div>
                    <div class="text-3xl font-bold text-indigo-400" id="straddle-cost">--</div>
                </div>
                <!-- Win Zone -->
                <div class="col-span-2">
                    <div class="stat-label text-indigo-300 mb-1">Breakeven Range</div>
                    <div class="flex items-center space-x-2">
                        <span class="text-xl font-mono text-green-400" id="straddle-lower">--</span>
                        <span class="text-slate-500">⟷</span>
                        <span class="text-xl font-mono text-red-400" id="straddle-upper">--</span>
                    </div>
                </div>
            </div>
            
            <!-- Straddle Premium Chart -->
            <div id="premium-chart-container" class="mt-6 pt-6 border-t border-slate-700">
                 <div class="flex justify-between text-xs mb-2">
                    <span class="text-green-400">▼ Decay Zone (Profit)</span>
                    <span class="text-red-400">▲ Spike Zone (Loss)</span>
                 </div>
                 <div class="relative h-64 w-full">
                    <canvas id="straddleChart"></canvas>
                 </div>
            </div>
        </div>
    </div>

    <!-- Main OI Chart -->
    <div class="glass-panel p-4 rounded-xl mb-6">
        <h3 class="text-lg font-semibold text-slate-200 mb-4">OI Structure</h3>
        <div class="relative h-80 w-full">
            <canvas id="oiChart"></canvas>
        </div>
    </div>
    
    <!-- PCR Guide (Restored) -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs mb-8">
        <div class="glass-panel p-3 border-l-2 border-green-500 text-slate-300">
            <strong class="text-white block mb-1">PCR > 1.2 (Bullish)</strong>
            More Puts sold. Support is strong. Market likely to go UP or stay sideways.
        </div>
        <div class="glass-panel p-3 border-l-2 border-yellow-500 text-slate-300">
            <strong class="text-white block mb-1">PCR 0.8 - 1.2 (Neutral)</strong>
            Balanced selling. Ideal for Strangles.
        </div>
        <div class="glass-panel p-3 border-l-2 border-red-500 text-slate-300">
            <strong class="text-white block mb-1">PCR < 0.8 (Bearish)</strong>
            More Calls sold. Resistance is strong. Market likely to go DOWN.
        </div>
    </div>

    <script>
        // --- TEST MODE ---
        const TEST_MODE = true; // Set to FALSE for real trading
        // ----------------

        let oiChart, straddleChart, strangleChart;
        let straddleHistory = { labels: [], data: [] }; 
        let strangleHistory = { labels: [], data: [] }; // NEW: Strangle History
        let initialStraddlePremium = null;
        let initialStranglePremium = null;

        function initOIChart() {
            const ctx = document.getElementById('oiChart').getContext('2d');
            oiChart = new Chart(ctx, {
                type: 'bar',
                data: { labels: [], datasets: [
                    { label: 'Call OI', data: [], backgroundColor: '#ef4444', order: 2 },
                    { label: 'Put OI', data: [], backgroundColor: '#22c55e', order: 3 },
                    { type: 'line', label: 'Call Vol', data: [], borderColor: '#ef4444', borderWidth: 1, yAxisID: 'y1', order:0 },
                    { type: 'line', label: 'Put Vol', data: [], borderColor: '#22c55e', borderWidth: 1, yAxisID: 'y1', order:1 }
                ]},
                options: {
                    responsive: true, maintainAspectRatio: false,
                    scales: {
                        x: { display: true, grid: { display: false } },
                        y: { display: true },
                        y1: { display: false }
                    }
                }
            });
        }

        function initStraddleChart() {
            const ctx = document.getElementById('straddleChart').getContext('2d');
            straddleChart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: 'Straddle Premium',
                        data: [],
                        borderColor: '#818cf8',
                        backgroundColor: 'rgba(129, 140, 248, 0.1)',
                        fill: true,
                        tension: 0.4
                    }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { display: false } }
                }
            });
        }
        
        // NEW: Strangle Chart Init
        function initStrangleChart() {
            const ctx = document.getElementById('strangleChart').getContext('2d');
            strangleChart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: 'Strangle Premium',
                        data: [],
                        borderColor: '#38bdf8', // Light Blue
                        backgroundColor: 'rgba(56, 189, 248, 0.1)',
                        fill: true,
                        tension: 0.4
                    }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                         x: { display: true, grid: { display: false }, ticks: { color: '#64748b' } },
                         y: { display: true, grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#64748b' } }
                    }
                }
            });
        }

        function toggleStraddleChart() {
            const container = document.getElementById('premium-chart-container');
            const checkbox = document.getElementById('chart-toggle');
            if(checkbox.checked) {
                container.classList.remove('hidden');
            } else {
                container.classList.add('hidden');
            }
        }
        
        function toggleStrangleChart() {
            const container = document.getElementById('strangle-premium-chart-container');
            const checkbox = document.getElementById('strangle-chart-toggle');
            if(checkbox.checked) {
                container.classList.remove('hidden');
            } else {
                container.classList.add('hidden');
            }
        }

        async function updateDashboard(manualRefresh = false) {
            try {
                if(manualRefresh) {
                   const btn = document.querySelector('button[title="Force Refresh"]');
                   if(btn) btn.classList.add('animate-spin');
                }
                
                const res = await fetch('/api/data');
                const data = await res.json();
                
                if(manualRefresh) {
                   const btn = document.querySelector('button[title="Force Refresh"]');
                   if(btn) btn.classList.remove('animate-spin');
                }

                if(!data || !data.metrics) return;

                // Basic UI Updates
                document.getElementById('spot-price').innerText = data.nifty_spot.toFixed(2);
                document.getElementById('wall-res').innerText = data.metrics.resistance;
                document.getElementById('wall-supp').innerText = data.metrics.support;
                document.getElementById('rec-call').innerText = data.strangle_intel.rec_call;
                document.getElementById('rec-put').innerText = data.strangle_intel.rec_put;
                document.getElementById('est-credit').innerText = "₹" + data.strangle_intel.est_credit.toFixed(2);
                document.getElementById('max-pain').innerText = data.metrics.max_pain;
                document.getElementById('pcr-val').innerText = data.metrics.pcr;

                const istTimeStr = data.timestamp;
                const [hh, mm] = istTimeStr.split(':').map(Number);
                let isAfter930 = (hh > 9) || (hh === 9 && mm >= 30);
                
                if (TEST_MODE) { isAfter930 = true; }
                
                const straddleCont = document.getElementById('straddle-container');
                const timeStatus = document.getElementById('time-status');

                // --- UPDATE STRANGLE CHART ---
                if(data.strangle_intel) {
                     const strangleCost = data.strangle_intel.est_credit;
                     if(initialStranglePremium === null) initialStranglePremium = strangleCost;
                     
                     const lastLabel = strangleHistory.labels[strangleHistory.labels.length - 1];
                     // Only update if time changed (simple de-dupe for rapid polls)
                     if (lastLabel !== istTimeStr.substring(0, 5)) {
                         strangleHistory.labels.push(istTimeStr.substring(0, 5));
                         strangleHistory.data.push(strangleCost);
                         
                         if(strangleHistory.labels.length > 60) {
                            strangleHistory.labels.shift();
                            strangleHistory.data.shift();
                         }
                         
                         strangleChart.data.labels = strangleHistory.labels;
                         strangleChart.data.datasets[0].data = strangleHistory.data;
                         
                         // Red/Green Zone
                         const color = strangleCost < initialStranglePremium ? '#4ade80' : '#f87171';
                         strangleChart.data.datasets[0].borderColor = color;
                         strangleChart.data.datasets[0].backgroundColor = strangleCost < initialStranglePremium ? 'rgba(74, 222, 128, 0.1)' : 'rgba(248, 113, 113, 0.1)';
                         
                         strangleChart.update('none');
                     }
                }

                // --- UPDATE STRADDLE ---
                if (isAfter930) {
                    straddleCont.classList.remove('opacity-50', 'grayscale', 'pointer-events-none');
                    if (TEST_MODE) {
                        timeStatus.innerText = "⚠️ TEST MODE (Ignoring Time)";
                        timeStatus.className = "ml-2 text-xs text-orange-400 font-bold";
                    } else {
                        timeStatus.innerText = "✅ ACTIVE (Live Data)";
                        timeStatus.className = "ml-2 text-xs text-green-400 font-bold";
                    }

                    if(data.straddle_intel) {
                        const cost = data.straddle_intel.cost;
                        document.getElementById('straddle-atm').innerText = data.straddle_intel.atm_strike;
                        document.getElementById('straddle-cost').innerText = "₹" + cost.toFixed(2);
                        document.getElementById('straddle-lower').innerText = data.straddle_intel.lower_be.toFixed(0);
                        document.getElementById('straddle-upper').innerText = data.straddle_intel.upper_be.toFixed(0);

                        // --- Straddle Chart Data ---
                        if (initialStraddlePremium === null) {
                            initialStraddlePremium = cost;
                        }

                        const lastLabel = straddleHistory.labels[straddleHistory.labels.length - 1];
                        if (lastLabel !== istTimeStr.substring(0, 5)) { 
                            straddleHistory.labels.push(istTimeStr.substring(0, 5));
                            straddleHistory.data.push(cost);
                            
                            if(straddleHistory.labels.length > 60) {
                                straddleHistory.labels.shift();
                                straddleHistory.data.shift();
                            }

                            straddleChart.data.labels = straddleHistory.labels;
                            straddleChart.data.datasets[0].data = straddleHistory.data;
                            
                            const color = cost < initialStraddlePremium ? '#4ade80' : '#f87171';
                            straddleChart.data.datasets[0].borderColor = color;
                            straddleChart.data.datasets[0].backgroundColor = cost < initialStraddlePremium ? 'rgba(74, 222, 128, 0.1)' : 'rgba(248, 113, 113, 0.1)';
                            
                            straddleChart.update('none');
                        }
                    }
                } else {
                    timeStatus.innerText = "(Waiting... Current IST: " + istTimeStr + ")";
                }

                // Update OI Chart
                oiChart.data.labels = data.chart_data.strikes;
                oiChart.data.datasets[0].data = data.chart_data.ce_oi;
                oiChart.data.datasets[1].data = data.chart_data.pe_oi;
                oiChart.data.datasets[2].data = data.chart_data.ce_vol;
                oiChart.data.datasets[3].data = data.chart_data.pe_vol;
                oiChart.update('none');

            } catch (e) {
                console.error("Sync Error", e);
            }
        }

        // INIT
        initOIChart();
        initStraddleChart();
        initStrangleChart(); // Start Strangle Chart
        
        // Ensure chart visibility matches toggle on load
        toggleStraddleChart(); 
        toggleStrangleChart();
        
        setInterval(() => updateDashboard(false), 2000);
        updateDashboard(false);
    </script>
</body>
</html>
`;

app.get('/', (req, res) => res.send(getHtml()));
app.get('/api/data', async (req, res) => {
    try {
        const response = await axios.get('http://127.0.0.1:8000/analyze');
        res.json(response.data);
    } catch (error) {
        res.status(502).json({ error: "Backend Offline" });
    }
});

app.listen(PORT, () => console.log("Dashboard running on http://localhost:" + PORT));