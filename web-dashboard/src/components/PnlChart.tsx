import { type PnlDay } from '../types';
import {
    ResponsiveContainer,
    AreaChart,
    Area,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
} from 'recharts';
import { TrendingUp } from 'lucide-react';

interface PnlChartProps {
    data: PnlDay[];
}

export function PnlChart({ data }: PnlChartProps) {
    // Compute cumulative PnL for the chart
    let cumulative = 0;
    const chartData = data.map((d) => {
        cumulative += d.realized_pnl || 0;
        return {
            date: d.date,
            daily: d.realized_pnl || 0,
            cumulative: Math.round(cumulative * 100) / 100,
            trades: d.trades || 0,
        };
    });

    return (
        <div className="rounded-xl border border-border bg-surface/50 backdrop-blur-md p-6">
            <h3 className="text-lg font-bold flex items-center gap-2 mb-6 text-textDim">
                <TrendingUp className="w-5 h-5" />
                PNL HISTORY
                <span className="ml-auto text-[10px] font-mono tracking-widest uppercase opacity-50">
                    {data.length} DAYS
                </span>
            </h3>

            {data.length === 0 ? (
                <div className="h-[200px] flex items-center justify-center">
                    <p className="text-textDim font-mono text-xs opacity-30">
                        NO PNL DATA YET
                    </p>
                </div>
            ) : (
                <ResponsiveContainer width="100%" height={220}>
                    <AreaChart data={chartData}>
                        <defs>
                            <linearGradient
                                id="pnlGradient"
                                x1="0"
                                y1="0"
                                x2="0"
                                y2="1"
                            >
                                <stop
                                    offset="5%"
                                    stopColor="#00ff41"
                                    stopOpacity={0.3}
                                />
                                <stop
                                    offset="95%"
                                    stopColor="#00ff41"
                                    stopOpacity={0}
                                />
                            </linearGradient>
                        </defs>
                        <CartesianGrid
                            strokeDasharray="3 3"
                            stroke="#333333"
                            opacity={0.3}
                        />
                        <XAxis
                            dataKey="date"
                            tick={{ fill: '#a0a0a0', fontSize: 10 }}
                            tickLine={false}
                            axisLine={{ stroke: '#333333' }}
                        />
                        <YAxis
                            tick={{ fill: '#a0a0a0', fontSize: 10 }}
                            tickLine={false}
                            axisLine={{ stroke: '#333333' }}
                            tickFormatter={(v) => `$${v}`}
                        />
                        <Tooltip
                            contentStyle={{
                                backgroundColor: '#121212',
                                border: '1px solid #333333',
                                borderRadius: '8px',
                                fontSize: '12px',
                                fontFamily: 'monospace',
                            }}
                            labelStyle={{ color: '#a0a0a0' }}
                            formatter={(value: number, name: string) => [
                                `$${value.toFixed(2)}`,
                                name === 'cumulative'
                                    ? 'Cumulative PnL'
                                    : 'Daily PnL',
                            ]}
                        />
                        <Area
                            type="monotone"
                            dataKey="cumulative"
                            stroke="#00ff41"
                            strokeWidth={2}
                            fill="url(#pnlGradient)"
                        />
                    </AreaChart>
                </ResponsiveContainer>
            )}
        </div>
    );
}
