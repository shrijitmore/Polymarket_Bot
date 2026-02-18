import clsx from 'clsx';
import { motion } from 'framer-motion';
import { type LucideIcon } from 'lucide-react';

interface MetricCardProps {
    label: string;
    value: string | number;
    subValue?: string;
    icon: LucideIcon;
    trend?: 'up' | 'down' | 'neutral';
    color?: 'primary' | 'secondary' | 'accent';
}

export function MetricCard({ label, value, subValue, icon: Icon, color = 'primary' }: MetricCardProps) {
    const colorClasses = {
        primary: 'text-[#00ff41] border-[#00ff41]/30 bg-[#00ff41]/5',
        secondary: 'text-[#00b8ff] border-[#00b8ff]/30 bg-[#00b8ff]/5',
        accent: 'text-[#ff0055] border-[#ff0055]/30 bg-[#ff0055]/5',
    };

    return (
        <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className={clsx(
                "relative overflow-hidden rounded-xl border p-6 backdrop-blur-sm",
                colorClasses[color]
            )}
        >
            <div className="flex items-start justify-between">
                <div>
                    <p className="text-sm font-medium opacity-70 uppercase tracking-wider">{label}</p>
                    <div className="mt-2 flex items-baseline gap-2">
                        <span className="text-3xl font-bold font-mono tracking-tight text-glow">
                            {value}
                        </span>
                        {subValue && (
                            <span className="text-sm opacity-60 font-mono">
                                {subValue}
                            </span>
                        )}
                    </div>
                </div>
                <div className={clsx("p-2 rounded-lg bg-black/20", colorClasses[color].split(' ')[0])}>
                    <Icon className="w-6 h-6" />
                </div>
            </div>

            {/* Decorative scanline */}
            <div className="absolute inset-0 bg-gradient-to-b from-transparent via-white/5 to-transparent h-[1px] w-full animate-scan" style={{ top: '50%' }} />
        </motion.div>
    );
}
