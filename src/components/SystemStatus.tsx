import React, { useState, useEffect } from 'react';
import { tradingBackend } from '../services/tradingBackend';

export function SystemStatus() {
  const [status, setStatus] = useState<any>(null);

  useEffect(() => {
    loadStatus();
    const interval = setInterval(loadStatus, 10000);
    return () => clearInterval(interval);
  }, []);

  const loadStatus = async () => {
    const data = await tradingBackend.getSystemStatus();
    setStatus(data);
  };

  if (!status) return null;

  return (
    <div className="glass-panel p-4 rounded-lg border-l-4 border-blue-500">
      <div className="flex items-center justify-between">
        <div>
          <div className="stat-label">System Status</div>
          <div className="flex items-center gap-4 mt-2">
            <div className="flex items-center gap-2">
              <span className={`h-2 w-2 rounded-full ${status.python.available ? 'bg-green-500' : 'bg-red-500'}`} />
              <span className="text-sm text-slate-300">Python Analytics</span>
            </div>
            <div className="flex items-center gap-2">
              <span className={`h-2 w-2 rounded-full ${status.go.available ? 'bg-green-500' : 'bg-red-500'}`} />
              <span className="text-sm text-slate-300">Go Execution</span>
            </div>
          </div>
        </div>
        
        <div className="text-right">
          <div className="stat-label">Active Backend</div>
          <div className="text-sm font-bold text-white mt-1">
            {status.activeBackend === 'go' ? 'Go API' : 'Python API'}
          </div>
        </div>
      </div>
    </div>
  );
}


// ============================================
// File: src/App.tsx
// Main dashboard layout
// ============================================

import React from 'react';
import { PositionsTable } from './components/PositionsTable';
import { ExecutionPanel } from './components/ExecutionPanel';
import { SystemStatus } from './components/SystemStatus';

function App() {
  return (
    <div className="min-h-screen bg-slate-900 p-8">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex justify-between items-center">
          <div>
            <h1 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-indigo-400 to-cyan-400">
              NIFTY Options Master
            </h1>
            <p className="text-slate-400 text-sm">Hybrid Backend Architecture</p>
          </div>
        </div>

        {/* System Status */}
        <SystemStatus />

        {/* Execution Panel */}
        <ExecutionPanel />

        {/* Positions Table */}
        <PositionsTable />
      </div>
    </div>
  );
}

export default App;