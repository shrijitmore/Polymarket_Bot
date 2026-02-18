import { type EventLog } from '../types';
import { format } from 'date-fns';
import { CheckCircle, XCircle, Clock, TrendingUp } from 'lucide-react';
import clsx from 'clsx';

interface ResolverLogProps {
    events: EventLog[];
}

interface ResolvedEntry {
    timestamp: string;
    positionId: string;
    strategy: string;
    winner: string;
    pnl: number;
    message: string;
}

function parseResolverEvent(ev: EventLog): ResolvedEntry | null {
    if (ev.event_type !== 'position_resolved') return null;
    const d = ev.details as Record<string, unknown>;
    const pnl = typeof d.realized_pnl === 'number' ? d.realized_pnl : 0;
    return {
        timestamp: ev.timestamp,
        positionId: String(d.position_id ?? '—'),
        strategy: String(d.strategy ?? '—'),
        winner: String(d.winner ?? '—'),
        pnl,
        message: String(d.message ?? ''),
    };
}

const strategyLabel: Record<string, string> = {
    yes_no: 'YES/NO',
    one_of_many: '1-OF-N',
    late_market: 'LATE',
};

export function ResolverLog({ events }: ResolverLogProps) {
    const resolved = events
        .map(parseResolverEvent)
        .filter((e): e is ResolvedEntry => e !== null);

    const totalPnl = resolved.reduce((sum, e) => sum + e.pnl, 0);
    const wins = resolved.filter((e) => e.pnl > 0).length;

    return (
        <div className="rounded-xl border border-border bg-surface/50 backdrop-blur-md p-6 flex flex-col gap-4">
            {/* Header */}
            <div className="flex items-center justify-between">
                <h3 className="text-lg font-bold flex items-center gap-2 text-textDim">
                    <TrendingUp className="w-5 h-5 text-primary" />
                    RESOLVER LOG
                    <span className="ml-2 text-[10px] font-mono tracking-widest uppercase opacity-50">
                        LIVE
                    </span>
                </h3>
                {resolved.length > 0 && (
                    <div className="flex items-center gap-3 text-xs font-mono">
                        <span className="text-textDim">
                            {wins}/{resolved.length} wins
                        </span>
                        <span
                            className={clsx(
                                'font-bold',
                                totalPnl >= 0 ? 'text-primary' : 'text-accent'
                            )}
                        >
                            {totalPnl >= 0 ? '+' : ''}${totalPnl.toFixed(4)}
                        </span>
                    </div>
                )}
            </div>

            {/* Entries */}
            <div className="flex flex-col gap-2 overflow-y-auto max-h-[420px] scrollbar-thin">
                {resolved.length === 0 && (
                    <div className="flex flex-col items-center justify-center py-12 gap-3 opacity-30">
                        <Clock className="w-8 h-8 text-textDim" />
                        <p className="text-textDim font-mono text-xs tracking-widest uppercase">
                            Awaiting market resolution...
                        </p>
                    </div>
                )}

                {resolved.map((entry, i) => {
                    const profit = entry.pnl >= 0;
                    const time = (() => {
                        try {
                            return format(new Date(entry.timestamp), 'HH:mm:ss');
                        } catch {
                            return '--:--:--';
                        }
                    })();

                    return (
                        <div
                            key={`${entry.timestamp}-${i}`}
                            className={clsx(
                                'rounded-lg border px-4 py-3 flex flex-col gap-1.5 transition-all',
                                profit
                                    ? 'border-primary/30 bg-primary/5 hover:bg-primary/10'
                                    : 'border-accent/30 bg-accent/5 hover:bg-accent/10'
                            )}
                        >
                            {/* Top row */}
                            <div className="flex items-center gap-2">
                                {profit ? (
                                    <CheckCircle className="w-4 h-4 text-primary shrink-0" />
                                ) : (
                                    <XCircle className="w-4 h-4 text-accent shrink-0" />
                                )}
                                <span
                                    className={clsx(
                                        'text-sm font-bold',
                                        profit ? 'text-primary' : 'text-accent'
                                    )}
                                >
                                    {profit ? '+' : ''}${entry.pnl.toFixed(4)}
                                </span>
                                <span className="ml-auto text-[10px] font-mono text-textDim opacity-60">
                                    [{time}]
                                </span>
                            </div>

                            {/* Details row */}
                            <div className="flex items-center gap-2 flex-wrap">
                                <span className="text-[10px] font-mono px-1.5 py-0.5 rounded border border-border bg-background text-textDim uppercase tracking-wider">
                                    {strategyLabel[entry.strategy] ?? entry.strategy}
                                </span>
                                <span className="text-[10px] font-mono text-textDim truncate max-w-[140px]">
                                    {entry.positionId}
                                </span>
                                <span className="ml-auto text-[10px] font-mono text-textDim">
                                    Winner:{' '}
                                    <span className="text-text font-bold">
                                        {entry.winner}
                                    </span>
                                </span>
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}
