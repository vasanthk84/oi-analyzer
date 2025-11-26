import React, { useState, useEffect } from 'react';
import { tradingBackend, StrangleRecommendation } from '../services/tradingBackend';

type Profile = 'conservative' | 'moderate' | 'aggressive';

export function ExecutionPanel() {
  const [profile, setProfile] = useState<Profile>('moderate');
  const [recommendation, setRecommendation] = useState<StrangleRecommendation | null>(null);
  const [quantity, setQuantity] = useState(50);
  const [isExecuting, setIsExecuting] = useState(false);
  const [autoTrade, setAutoTrade] = useState(false);
  const [isGoAPIEnabled, setIsGoAPIEnabled] = useState(false);

  useEffect(() => {
    // Check if Go API is available
    tradingBackend.getSystemStatus().then(status => {
      setIsGoAPIEnabled(status.go.available);
    });

    // Fetch analysis
    loadAnalysis();
    
    // Refresh every 5 seconds
    const interval = setInterval(loadAnalysis, 5000);
    return () => clearInterval(interval);
  }, [profile]);

  const loadAnalysis = async () => {
    try {
      const analysis = await tradingBackend.getAnalysis();
      setRecommendation(analysis.strangle_intel[profile]);
    } catch (error) {
      console.error('Failed to load analysis:', error);
    }
  };

  const handleExecute = async () => {
    if (!recommendation) return;
    
    const confirmed = confirm(
      `Execute Strangle?\n\n` +
      `Call Strike: ${recommendation.rec_call}\n` +
      `Put Strike: ${recommendation.rec_put}\n` +
      `Credit: ₹${recommendation.est_credit.toFixed(2)}\n` +
      `Quantity: ${quantity}\n` +
      `Auto-Trade: ${autoTrade ? 'Enabled' : 'Disabled'}\n\n` +
      `Proceed?`
    );
    
    if (!confirmed) return;

    setIsExecuting(true);
    try {
      const result = await tradingBackend.executeStrangle(
        recommendation.rec_call,
        recommendation.rec_put,
        quantity,
        { profile, autoTrade }
      );

      if (result.success) {
        alert(`✅ ${result.message}\n\nCall: ${result.callOrder?.orderId || 'N/A'}\nPut: ${result.putOrder?.orderId || 'N/A'}`);
      } else {
        alert(`❌ Execution Failed\n\n${result.error || result.message}`);
      }
    } catch (error) {
      alert('❌ Execution failed: ' + (error as Error).message);
    } finally {
      setIsExecuting(false);
    }
  };

  if (!recommendation) {
    return (
      <div className="glass-panel p-6 rounded-xl">
        <div className="animate-pulse">Loading recommendations...</div>
      </div>
    );
  }

  const liquidityWarning = !recommendation.call_stats.ok || !recommendation.put_stats.ok;

  return (
    <div className="glass-panel p-6 rounded-xl border-t-4 border-blue-500">
      {/* Profile Selector */}
      <div className="flex justify-between items-center mb-6">
        <h3 className="text-lg font-bold text-white">Smart Execution</h3>
        <div className="bg-slate-800 p-1 rounded-lg flex">
          {(['conservative', 'moderate', 'aggressive'] as Profile[]).map(p => (
            <button
              key={p}
              onClick={() => setProfile(p)}
              className={`px-3 py-1 text-xs rounded transition ${
                profile === p 
                  ? 'bg-blue-600 text-white' 
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              {p.charAt(0).toUpperCase() + p.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* Strikes Display */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="text-center">
          <div className="stat-label text-red-400">Call Strike</div>
          <div className="text-3xl font-bold text-white">{recommendation.rec_call}</div>
          <div className="text-xs text-slate-400 mt-1">
            Δ {recommendation.call_greeks.delta.toFixed(3)}
          </div>
        </div>
        
        <div className="text-center">
          <div className="stat-label text-blue-400">Est. Credit</div>
          <div className="text-3xl font-bold text-blue-400">
            ₹{recommendation.est_credit.toFixed(2)}
          </div>
          <div className="text-xs text-slate-400 mt-1">
            Per lot ({quantity} qty)
          </div>
        </div>
        
        <div className="text-center">
          <div className="stat-label text-green-400">Put Strike</div>
          <div className="text-3xl font-bold text-white">{recommendation.rec_put}</div>
          <div className="text-xs text-slate-400 mt-1">
            Δ {recommendation.put_greeks.delta.toFixed(3)}
          </div>
        </div>
      </div>

      {/* Liquidity Warning */}
      {liquidityWarning && (
        <div className="bg-yellow-900/30 border border-yellow-600 rounded-lg p-3 mb-4">
          <div className="flex items-center gap-2 text-yellow-400 text-sm">
            <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
            </svg>
            <span>Low liquidity detected. Check order flow before execution.</span>
          </div>
        </div>
      )}

      {/* Execution Controls */}
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div>
          <label className="stat-label block mb-2">Quantity (Lots)</label>
          <input
            type="number"
            value={quantity}
            onChange={(e) => setQuantity(Number(e.target.value))}
            min={25}
            step={25}
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded text-white"
          />
        </div>
        
        <div>
          <label className="stat-label block mb-2">Auto-Trade {isGoAPIEnabled ? '' : '(Go API Required)'}</label>
          <button
            onClick={() => setAutoTrade(!autoTrade)}
            disabled={!isGoAPIEnabled}
            className={`w-full px-3 py-2 rounded font-medium transition ${
              autoTrade 
                ? 'bg-green-600 text-white' 
                : 'bg-slate-700 text-slate-400'
            } ${!isGoAPIEnabled ? 'opacity-50 cursor-not-allowed' : 'hover:bg-green-700'}`}
          >
            {autoTrade ? 'Enabled ✓' : 'Disabled'}
          </button>
        </div>
      </div>

      {/* Execute Button */}
      <button
        onClick={handleExecute}
        disabled={isExecuting}
        className="w-full py-3 bg-gradient-to-r from-red-600 to-red-700 hover:from-red-700 hover:to-red-800 text-white font-bold rounded-lg transition-all shadow-lg disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {isExecuting ? 'Executing...' : `Execute Strangle (${quantity} lots)`}
      </button>

      {/* Backend Info */}
      <div className="mt-4 text-xs text-slate-500 text-center">
        Using: {isGoAPIEnabled ? 'Go API (Managed)' : 'Python API (Manual)'} | 
        Profile: {profile} | 
        Auto-Trade: {autoTrade ? 'ON' : 'OFF'}
      </div>
    </div>
  );
}