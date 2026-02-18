import { type Position } from '../types';
import { format } from 'date-fns';
import clsx from 'clsx';

interface PositionsTableProps {
    positions: Position[];
}

export function PositionsTable({ positions }: PositionsTableProps) {
    return (
        <div className="w-full overflow-hidden rounded-xl border border-border bg-surface/50 backdrop-blur-md">
            <div className="px-6 py-4 border-b border-border flex justify-between items-center bg-black/20">
                <h3 className="text-lg font-bold text-primary flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-primary animate-pulse shadow-[0_0_10px_#00ff41]" />
                    POSITIONS
                </h3>
                <span className="text-xs text-textDim font-mono uppercase tracking-widest">
                    LIVE FEED &bull; {positions.filter(p => p.status === 'open').length} ACTIVE
                </span>
            </div>

            <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                    <thead className="bg-surfaceHighlight/50 text-textDim font-mono uppercase text-xs tracking-wider border-b border-border/50">
                        <tr>
                            <th className="px-6 py-4">Time</th>
                            <th className="px-6 py-4">Market</th>
                            <th className="px-6 py-4">Strategy</th>
                            <th className="px-6 py-4 text-right">Size ($)</th>
                            <th className="px-6 py-4 text-right">Edge %</th>
                            <th className="px-6 py-4 text-right">PnL</th>
                            <th className="px-6 py-4 text-center">Status</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-border/30">
                        {positions.map((pos) => {
                            const pnl = pos.realized_pnl;
                            const hasPnl = pnl !== undefined && pnl !== null;
                            return (
                                <tr key={pos.position_id} className="hover:bg-white/5 transition-colors group">
                                    <td className="px-6 py-4 font-mono text-xs text-textDim group-hover:text-text transition-colors">
                                        {(() => {
                                            try {
                                                return format(new Date(pos.opened_at), 'HH:mm:ss');
                                            } catch {
                                                return '--:--:--';
                                            }
                                        })()}
                                    </td>
                                    <td className="px-6 py-4 font-medium max-w-[280px] truncate text-text group-hover:text-primary transition-colors" title={pos.question}>
                                        {pos.question}
                                    </td>
                                    <td className="px-6 py-4">
                                        <span className={clsx(
                                            "px-2 py-1 rounded text-[10px] font-bold uppercase tracking-wide border",
                                            pos.strategy === 'late_market' ? "bg-purple-500/10 text-purple-400 border-purple-500/20" :
                                                pos.strategy === 'one_of_many' ? "bg-blue-500/10 text-blue-400 border-blue-500/20" :
                                                    "bg-yellow-500/10 text-yellow-400 border-yellow-500/20"
                                        )}>
                                            {pos.strategy?.replace('_', ' ') ?? 'unknown'}
                                        </span>
                                    </td>
                                    <td className="px-6 py-4 text-right font-mono text-text">
                                        ${pos.total_cost?.toFixed(2) ?? '0.00'}
                                    </td>
                                    <td className="px-6 py-4 text-right font-mono text-primary font-bold">
                                        {pos.expected_edge?.toFixed(2) ?? '0.00'}%
                                    </td>
                                    <td className={clsx(
                                        "px-6 py-4 text-right font-mono font-bold",
                                        !hasPnl ? "text-textDim" :
                                            pnl > 0 ? "text-primary" :
                                                pnl < 0 ? "text-accent" : "text-textDim"
                                    )}>
                                        {hasPnl ? (pnl >= 0 ? '+' : '') + `$${pnl.toFixed(2)}` : '-'}
                                    </td>
                                    <td className="px-6 py-4">
                                        <div className="flex items-center justify-center gap-2">
                                            <span className={clsx(
                                                "w-1.5 h-1.5 rounded-full",
                                                pos.status === 'open' ? "bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.8)] animate-pulse" :
                                                    pos.status === 'closed' ? "bg-gray-500" :
                                                        "bg-yellow-500"
                                            )} />
                                            <span className="capitalize text-xs font-medium tracking-wide text-textDim group-hover:text-text transition-colors">{pos.status}</span>
                                        </div>
                                    </td>
                                </tr>
                            );
                        })}
                        {positions.length === 0 && (
                            <tr>
                                <td colSpan={7} className="px-6 py-16 text-center text-textDim font-mono text-sm">
                                    <div className="flex flex-col items-center gap-3 opacity-50">
                                        <div className="w-12 h-12 rounded-full border-2 border-dashed border-textDim flex items-center justify-center animate-spin-slow">
                                            <div className="w-2 h-2 bg-textDim rounded-full" />
                                        </div>
                                        <span>NO POSITIONS FOUND</span>
                                        <span className="text-xs">SCANNING MARKETS...</span>
                                    </div>
                                </td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
