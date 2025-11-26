// ============================================
// File: src/components/PositionsTable.tsx
// Real-time positions with SSE
// ============================================

import React, { useState, useEffect } from 'react';
import { tradingBackend, Position } from '../services/tradingBackend';

export function PositionsTable() {
    const [positions, setPositions] = useState<Position[]>([]);
    const [totalMtm, setTotalMtm] = useState(0);
    const [isConnected, setIsConnected] = useState(false);
    const [isLoading, setIsLoading] = useState(true);

    useEffect(() => {
        // Subscribe to real-time position updates
        const unsubscribe = tradingBackend.subscribeToPositions((data) => {
            setPositions(data.positions);
            setTotalMtm(data.total_mtm);
            setIsConnected(true);
            setIsLoading(false);
        });

        // Cleanup on unmount
        return () => {
            unsubscribe();
            setIsConnected(false);
        };
    }, []);

    const handleClosePosition = async (symbol: string, quantity: number) => {
        if (!confirm(`Close position ${symbol}?`)) return;

        try {
            const result = await tradingBackend.closePosition(symbol, Math.abs(quantity));
            if (result.success) {
                alert('✅ Position closed successfully');
            } else {
                alert('❌ ' + result.message);
            }
        } catch (error) {
            alert('❌ Failed to close position');
        }
    };

    const handleCloseAll = async () => {
        if (!confirm('Close ALL positions?')) return;

        try {
            const result = await tradingBackend.closeAllPositions();
            if (result.success) {
                alert(`✅ Closed ${result.message}`);
            } else {
                alert('❌ ' + result.message);
            }
        } catch (error) {
            alert('❌ Failed to close all positions');
        }
    };

    if (isLoading) {
        return (
            <div className="glass-panel p-6 rounded-xl">
                <div className="animate-pulse">Loading positions...</div>
            </div>
        );
    }

    return (
        <div className="glass-panel rounded-xl overflow-hidden">
            {/* Header */}
            <div className="flex justify-between items-center p-4 border-b border-slate-700">
                <div className="flex items-center gap-3">
                    <h3 className="text-lg font-bold text-white">Live Positions</h3>
                    <div className="flex items-center gap-2">
                        <span className={`h-2 w-2 rounded-full ${isConnected ? 'bg-green-500 animate-pulse' : 'bg-red-500'}`} />
                        <span className="text-xs text-slate-400">
                            {isConnected ? 'Live' : 'Disconnected'}
                        </span>
                    </div>
                </div>

                {positions.length > 0 && (
                    <button
                        onClick={handleCloseAll}
                        className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white text-sm font-bold rounded-lg transition"
                    >
                        Close All
                    </button>
                )}
            </div>

            {/* Table */}
            {positions.length === 0 ? (
                <div className="p-8 text-center text-slate-400">
                    No open positions
                </div>
            ) : (
                <div className="overflow-x-auto">
                    <table className="w-full text-sm text-left">
                        <thead className="text-xs text-slate-300 uppercase bg-slate-700">
                            <tr>
                                <th className="px-4 py-3">Symbol</th>
                                <th className="px-4 py-3 text-right">Qty</th>
                                <th className="px-4 py-3 text-right">Avg Price</th>
                                <th className="px-4 py-3 text-right">LTP</th>
                                <th className="px-4 py-3 text-right">P&L</th>
                                <th className="px-4 py-3 text-right">Action</th>
                            </tr>
                        </thead>
                        <tbody>
                            {positions.map((pos, idx) => {
                                const pnl = pos.mtm || 0;
                                const pnlClass = pnl >= 0 ? 'text-green-400' : 'text-red-400';

                                return (
                                    <tr key={idx} className="border-b border-slate-800 hover:bg-slate-800/30 transition">
                                        <td className="px-4 py-3 text-white font-medium">{pos.tradingsymbol}</td>
                                        <td className="px-4 py-3 text-right text-slate-300">{pos.quantity}</td>
                                        <td className="px-4 py-3 text-right text-slate-300">{pos.average_price.toFixed(2)}</td>
                                        <td className="px-4 py-3 text-right text-white font-mono">{pos.last_price.toFixed(2)}</td>
                                        <td className={`px-4 py-3 text-right font-bold font-mono ${pnlClass}`}>
                                            {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}
                                        </td>
                                        <td className="px-4 py-3 text-right">
                                            <button
                                                onClick={() => handleClosePosition(pos.tradingsymbol, pos.quantity)}
                                                className="px-3 py-1 bg-slate-700 hover:bg-slate-600 text-white text-xs rounded transition"
                                            >
                                                Close
                                            </button>
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                        <tfoot className="bg-slate-800/50 font-bold text-slate-200">
                            <tr>
                                <td colSpan={4} className="px-4 py-3 text-right">Total MTM:</td>
                                <td
                                    colSpan={2}
                                    className={`px-4 py-3 text-right font-mono text-lg ${totalMtm >= 0 ? 'text-green-400' : 'text-red-400'}`}
                                >
                                    {totalMtm >= 0 ? '+' : ''}{totalMtm.toFixed(2)}
                                </td>
                            </tr>
                        </tfoot>
                    </table>
                </div>
            )}
        </div>
    );
}