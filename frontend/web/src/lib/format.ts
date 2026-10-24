import { format } from 'd3-format';
import { timeFormat, utcParse } from 'd3-time-format';

const compact = format('.3~s');
const int = format(',.0f');

export function num(v: number | null | undefined, digits = 0): string {
	if (v === null || v === undefined || !Number.isFinite(v)) return '–';
	const a = Math.abs(v);
	if (a >= 10_000) return compact(v).replace('G', 'B');
	if (a >= 1000 || digits === 0) return int(v);
	return v.toFixed(digits);
}

export function pct(v: number | null | undefined, digits = 0): string {
	if (v === null || v === undefined || !Number.isFinite(v)) return '–';
	return `${(v * 100).toFixed(digits)}%`;
}

export function fixed(v: number | null | undefined, digits = 2): string {
	if (v === null || v === undefined || !Number.isFinite(v)) return '–';
	return v.toFixed(digits);
}

export const parseDate = utcParse('%Y-%m-%d');
const short = timeFormat('%b %-d');
const long = timeFormat('%b %-d, %Y');

export function shortDate(s: string | undefined): string {
	const d = s ? parseDate(s) : null;
	return d ? short(d) : '–';
}
export function longDate(s: string | undefined): string {
	const d = s ? parseDate(s) : null;
	return d ? long(d) : '–';
}

export function days(v: number | null | undefined): string {
	if (v === null || v === undefined || !Number.isFinite(v)) return '–';
	return `${v.toFixed(1)} d`;
}
