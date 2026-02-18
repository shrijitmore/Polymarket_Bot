import { type EventLog } from '../types';
import { format } from 'date-fns';
import { Terminal } from 'lucide-react';
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
                    const message =
                        ev.details?.message ||
                        ev.details?.msg ||
                        ev.event_type.replace(/_/g, ' ');

                    return (
                        <div
                            key={`${ev.timestamp}-${i}`}
                            className="flex gap-2 leading-relaxed hover:bg-white/5 px-2 py-0.5 rounded transition-colors"
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
                            <span className={clsx('truncate', colorClass)}>
                                {String(message)}
                            </span>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}
