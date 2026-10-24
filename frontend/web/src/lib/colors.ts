// Colors by role. Compartment hues follow the entity everywhere on the site and
// were checked with the dataviz validator on the panel surface (#141416).
import { interpolateRgb, piecewise } from 'd3-interpolate';

export const COMPARTMENT: Record<string, string> = {
	S: '#3987e5',
	E: '#c98500',
	I: '#d55181',
	A: '#e87ba4',
	R: '#199e70',
	V: '#6da7ec',
	H: '#9085e9',
	C: '#d95926',
	D: '#e66767'
};

export const LABEL: Record<string, string> = {
	S: 'Susceptible',
	E: 'Exposed',
	I: 'Infectious',
	A: 'Asymptomatic',
	R: 'Recovered',
	V: 'Vaccinated',
	H: 'Ward',
	C: 'ICU',
	D: 'Deaths'
};

export const SERIES = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'];

export const STATUS = {
	good: '#0ca30c',
	warning: '#fab219',
	serious: '#ec835a',
	critical: '#d03b3b'
} as const;

export type Status = keyof typeof STATUS;

/** Hospital state from occupancy (share of staffed beds in use). */
export function occupancyStatus(occ: number, diverted = false): Status {
	if (diverted || occ >= 1) return 'critical';
	if (occ >= 0.95) return 'serious';
	if (occ >= 0.85) return 'warning';
	return 'good';
}

export const STATUS_LABEL: Record<Status, string> = {
	good: 'Normal',
	warning: 'Busy',
	serious: 'Nearly full',
	critical: 'Full, turning patients away'
};

// Sequential ramps for a dark surface: low values sit near the surface, high values glow.
const heat = piecewise(interpolateRgb.gamma(2.2), ['#1d1d22', '#5a2a1a', '#a5431c', '#d95926', '#f2a35e', '#ffe3bf']);
const cool = piecewise(interpolateRgb.gamma(2.2), ['#1d1d22', '#13304f', '#1c5cab', '#3987e5', '#86b6ef', '#dbeafe']);

export function heatColor(t: number): string {
	return heat(Math.max(0, Math.min(1, t)));
}
export function coolColor(t: number): string {
	return cool(Math.max(0, Math.min(1, t)));
}

/** Operability 0-100: 100 recedes, low values turn critical. */
export function operabilityColor(p: number): string {
	if (p >= 95) return '#2c2c30';
	if (p >= 85) return STATUS.warning;
	if (p >= 70) return STATUS.serious;
	return STATUS.critical;
}
