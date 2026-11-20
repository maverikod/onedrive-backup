import { readFileSync } from 'node:fs'
import vue from '@vitejs/plugin-vue'
import type { Plugin } from 'vite'
import { defineConfig } from 'vitest/config'
import { COMMANDS, NOT_USED } from './src/commands'

const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf-8')) as { version: string }

// The public file set is fixed and finite (PP-AUTH4): no content hashes in file names, one chunk.
function commandManifest(): Plugin {
  return {
    name: 'command-manifest',
    generateBundle() {
      const manifest = { version: pkg.version, used: COMMANDS, not_used: NOT_USED }
      this.emitFile({ type: 'asset', fileName: 'command-manifest.json', source: JSON.stringify(manifest, null, 2) + '\n' })
    },
  }
}

export default defineConfig({
  plugins: [vue(), commandManifest()],
  build: {
    target: 'es2022',
    sourcemap: false,
    cssCodeSplit: false,
    rollupOptions: {
      output: {
        entryFileNames: 'assets/app.js',
        chunkFileNames: 'assets/[name].js',
        assetFileNames: (info) => ((info.names ?? []).some((name) => name.endsWith('.css')) ? 'assets/app.css' : 'assets/[name][extname]'),
        inlineDynamicImports: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    include: ['tests/**/*.test.ts'],
  },
})
