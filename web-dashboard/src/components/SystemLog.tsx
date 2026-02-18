import { type EventLog } from '../types';
import { format } from 'date-fns';
import { Terminal, TrendingUp, TrendingDown } from 'lucide-react';
import clsx from 'clsx';

interface SystemLogProps {
    events: EventLog[];
}

const levelColors: Record<string, string> = {
    INFO: 'text-primary',
    WARNING: 'text-yellow-400',
    ERROR: 'text-accent',
    DEBUG: 'text-textDim',
};

function getEventIcon(ev: EventLog) {
    if (ev.event_type === 'position_resolved') {
        const pnl = (ev.details as Record<string, unknown>)?.realized_pnl;
        if (typeof pnl === 'number') {
            return pnl >= 0
                ? <TrendingUp className="w-3 h-3 text-primary shrink-0 mt-0.5" />
                : <TrendingDown className="w-3 h-3 text-accent shrink-0 mt-0.5" />;
        }
    }
    return null;
}

function formatMessage(ev: EventLog): string {
    const d = ev.details as Record<string, unknown>;
    if (ev.event_type === 'position_resolved') {
        const pnl = typeof d.realized_pnl === 'number' ? d.realized_pnl : 0;
        const winner = d.winner ?? '?';
        const strategy = d.strategy ?? '?';
        const sign = pnl >= 0 ? '+' : '';
        return `RESOLVED [${strategy}] winner=${winner} pnl=${sign}$${pnl.toFixed(4)}`;
    }
    return String(d?.message ?? d?.msg ?? ev.event_type.replace(/_/g, ' '));
}

export function SystemLog({ events }: SystemLogProps) {
    return (
        <div className="rounded-xl border border-border bg-surface/50 backdrop-blur-md p-6 h-full min-h-[400px] flex flex-col">
            <h3 className="text-lg font-bold flex items-center gap-2 mb-4 text-textDim">
                <Terminal className="w-5 h-5" />
                SYSTEM LOG
                <span className="ml-auto text-[10px] font-mono tracking-widest uppercase opacity-50">
                    LIVE
                </span>
            </h3>
            <div className="flex-1 overflow-y-auto font-mono text-xs space-y-1.5 scrollbar-thin">
                {events.length === 0 && (
                    <div className="flex items-center justify-center h-full opacity-30">
                        <p className="text-textDim">WAITING FOR EVENTS...</p>
                    </div>
                )}
                {events.map((ev, i) => {
                    const time = (() => {
                        try {
                            return format(new Date(ev.timestamp), 'HH:mm:ss');
                        } catch {
                            return '--:--:--';
                        }
                    })();
                    const colorClass = levelColors[ev.level] || 'text-textDim';
                    const message = formatMessage(ev);
                    const icon = getEventIcon(ev);
                    const isResolver = ev.event_type === 'position_resolved';

                    return (
                        <div
                            key={`${ev.timestamp}-${i}`}
                            className={clsx(
                                'flex gap-2 leading-relaxed px-2 py-0.5 rounded transition-colors',
                                isResolver
                                    ? 'bg-primary/5 border border-primary/10 hover:bg-primary/10'
                                    : 'hover:bg-white/5'
                            )}
                        >
                            <span className="text-textDim opacity-50 shrink-0">
                                [{time}]
                            </span>
                            <span
                                className={clsx(
                                    'font-bold uppercase shrink-0 w-14 text-right',
                                    colorClass
                                )}
                            >
                                {ev.level}
                            </span>
                            {icon}
                            <span className={clsx('truncate', colorClass)}>
                                {message}
                            </span>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}
