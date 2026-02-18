import { useEffect, useState, useCallback } from 'react';
import {
    Activity,
    DollarSign,
    TrendingUp,
    Zap,
    Trophy,
    Shield,
} from 'lucide-react';
import { MetricCard } from './components/MetricCard';
import { PositionsTable } from './components/PositionsTable';
import { SystemLog } from './components/SystemLog';
import { PnlChart } from './components/PnlChart';
import { ResolverLog } from './components/ResolverLog';
import { type Stats, type Position, type EventLog, type PnlDay } from './types';
import axios from 'axios';
import clsx from 'clsx';

const API_BASE = 'http://localhost:8000';

function App() {
    const [stats, setStats] = useState<Stats | null>(null);
    const [positions, setPositions] = useState<Position[]>([]);
    const [events, setEvents] = useState<EventLog[]>([]);
    const [pnlHistory, setPnlHistory] = useState<PnlDay[]>([]);
    const [isConnected, setIsConnected] = useState(false);

    // Initial data fetch
    const fetchInitialData = useCallback(async () => {
        try {
            const [statsRes, positionsRes, eventsRes, pnlRes] =
                await Promise.all([
                    axios.get(`${API_BASE}/api/stats`),
                    axios.get(`${API_BASE}/api/positions`),
                    axios.get(`${API_BASE}/api/events?limit=50`),
                    axios.get(`${API_BASE}/api/pnl-history?days=30`),
                ]);
            setStats(statsRes.data);
            setPositions(positionsRes.data);
            setEvents(eventsRes.data);
            setPnlHistory(pnlRes.data);
        } catch (err) {
            console.error('Failed to fetch initial data', err);
        }
    }, []);

    useEffect(() => {
        fetchInitialData();
    }, [fetchInitialData]);

    // WebSocket connection
    useEffect(() => {
        let ws: WebSocket;
        let reconnectTimeout: ReturnType<typeof setTimeout>;

        const connectWs = () => {
            ws = new WebSocket(`${API_BASE.replace('http', 'ws')}/ws`);

            ws.onopen = () => {
                setIsConnected(true);
                // Send keepalive ping
                ws.send('ping');
            };

            ws.onmessage = (event) => {
                try {
                    const message = JSON.parse(event.data);

                    if (message.type === 'full_update') {
                        const { stats: s, positions: p, events: e } =
                            message.data;
                        if (s) setStats(s);
                        if (p) setPositions(p);
                        if (e) setEvents((prev) => {
                            // Merge new events, keep last 50
                            const merged = [...e, ...prev];
                            const seen = new Set<string>();
                            return merged.filter((ev) => {
                                const key = `${ev.timestamp}-${ev.event_type}`;
                                if (seen.has(key)) return false;
                                seen.add(key);
                                return true;
                            }).slice(0, 50);
                        });
                    } else if (message.type === 'stats_update') {
                        // Backward compat with old format
                        setStats(message.data);
                    }
                } catch (err) {
                    console.error('WS parse error', err);
                }
            };

            ws.onclose = () => {
                setIsConnected(false);
                reconnectTimeout = setTimeout(connectWs, 3000);
            };

            ws.onerror = () => {
                ws.close();
            };
        };

        connectWs();

        return () => {
            clearTimeout(reconnectTimeout);
            ws?.close();
        };
    }, []);

    // Periodically refresh PnL history (every 30s)
    useEffect(() => {
        const interval = setInterval(async () => {
            try {
                const res = await axios.get(
                    `${API_BASE}/api/pnl-history?days=30`
                );
                setPnlHistory(res.data);
            } catch {
                // silent
            }
        }, 30000);
        return () => clearInterval(interval);
    }, []);

    const isDryRun = stats?.dry_run ?? true;

    return (
        <div className="min-h-screen bg-background text-text p-6 md:p-10 font-sans selection:bg-primary/30">
            {/* HEADER */}
            <header className="mb-10 flex flex-col md:flex-row md:items-center justify-between gap-6 pb-6 border-b border-border/40">
                <div>
                    <h1 className="text-4xl md:text-5xl font-bold tracking-tighter text-transparent bg-clip-text bg-gradient-to-r from-primary via-primaryDim to-secondary">
                        POLYMARKET MONEY PRINTER
                    </h1>
                    <p className="text-textDim font-mono text-xs tracking-wide uppercase mt-2 flex items-center gap-3">
                        BTC 5M ARBITRAGE SYSTEM
                        {isDryRun && (
                            <span className="px-2 py-0.5 rounded border border-yellow-500/30 bg-yellow-500/10 text-yellow-400 text-[10px] font-bold">
                                DRY RUN
                            </span>
                        )}
                    </p>
                </div>
                <div
                    className={clsx(
                        'flex items-center gap-3 px-4 py-2 rounded-full border border-border bg-surface',
                        isConnected ? 'text-primary' : 'text-red-500'
                    )}
                >
                    <div
                        className={clsx(
                            'w-2 h-2 rounded-full animate-pulse',
                            isConnected
                                ? 'bg-primary shadow-[0_0_10px_#00ff41]'
                                : 'bg-red-500'
                        )}
                    />
                    <span className="text-xs font-mono font-bold tracking-wider">
                        {isConnected ? 'SYSTEM ONLINE' : 'DISCONNECTED'}
                    </span>
                </div>
            </header>

            {/* METRIC CARDS */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4 mb-10">
                <MetricCard
                    label="Total Profit"
                    value={`$${stats?.total_pnl?.toFixed(2) ?? '0.00'}`}
                    subValue={
                        stats?.daily_pnl !== undefined
                            ? stats.daily_pnl >= 0
                                ? `+$${stats.daily_pnl.toFixed(2)} today`
                                : `-$${Math.abs(stats.daily_pnl).toFixed(2)} today`
                            : undefined
                    }
                    icon={DollarSign}
                    color="primary"
                />
                <MetricCard
                    label="Bankroll"
                    value={`$${stats?.bankroll?.toFixed(2) ?? '0.00'}`}
                    icon={Activity}
                    color="secondary"
                />
                <MetricCard
                    label="Active Trades"
                    value={stats?.active_positions ?? 0}
                    icon={Zap}
                    color="accent"
                />
                <MetricCard
                    label="Win Rate"
                    value={`${stats?.win_rate?.toFixed(1) ?? '0.0'}%`}
                    icon={TrendingUp}
                    color="primary"
                />
                <MetricCard
                    label="Total Trades"
                    value={stats?.total_trades ?? 0}
                    icon={Trophy}
                    color="secondary"
                />
                <MetricCard
                    label="Wins"
                    value={stats?.winning_trades ?? 0}
                    icon={Shield}
                    color="primary"
                />
            </div>

            {/* MAIN GRID */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                {/* Left: Positions + PnL Chart */}
                <div className="lg:col-span-2 space-y-8">
                    <PositionsTable positions={positions} />
                    <PnlChart data={pnlHistory} />
                </div>

                {/* Right: Resolver Log + System Log */}
                <div className="space-y-6">
                    <ResolverLog events={events} />
                    <SystemLog events={events} />
                </div>
            </div>
        </div>
    );
}

export default App;
