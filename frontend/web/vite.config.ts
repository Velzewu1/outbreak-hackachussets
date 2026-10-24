import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

const API = process.env.API_URL ?? 'http://127.0.0.1:8000';

export default defineConfig({
	plugins: [
		sveltekit({
			compilerOptions: {
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},
			// A single-page app: FastAPI (frontend/api) serves build/ and the JSON API together.
			adapter: adapter({ fallback: 'index.html' })
		})
	],
	server: { proxy: { '/api': API } },
	preview: { proxy: { '/api': API } }
});
