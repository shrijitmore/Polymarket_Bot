export interface Position {
    position_id: string;
    market_id: string;
    question: string;
    strategy: string;
    status: string;
    total_cost: number;
    expected_edge: number;
    opened_at: string;
    actual_edge?: number;
    realized_pnl?: number;
}

export interface Opportunity {
    market_id: string;
    question: string;
    strategy: string;
    edge_pct: number;
    expires_at: string;
}

export interface Stats {
    total_pnl: number;
    daily_pnl: number;
    bankroll: number;
    active_positions: number;
    win_rate: number;
    total_trades: number;
    winning_trades: number;
    status: string;
    dry_run: boolean;
}

export interface EventLog {
    timestamp: string;
    event_type: string;
    level: string;
    details: Record<string, unknown>;
}

export interface PnlDay {
    date: string;
    realized_pnl: number;
    unrealized_pnl?: number;
    trades?: number;
}
