import { request } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

// The gateway authenticates every request. The suite exchanges the local token (configs/api_token or XAU_API_TOKEN) for the HttpOnly session
// cookie exactly like a browser does, and stores it as the Playwright storage state used by every test.
export default async function globalSetup() {
  const base = process.env.XAU_BASE_URL ?? 'http://127.0.0.1:8765';
  const file = path.join('configs', 'api_token');
  const token = (process.env.XAU_API_TOKEN ?? (fs.existsSync(file) ? fs.readFileSync(file, 'utf8') : '')).trim();
  fs.mkdirSync('qa-artifacts', { recursive: true });
  const ctx = await request.newContext({ baseURL: base });
  const r = await ctx.get('/?token=' + encodeURIComponent(token), { maxRedirects: 0 });
  if (r.status() === 303) { await ctx.storageState({ path: 'qa-artifacts/auth-state.json' }); }
  else if (r.status() === 200) { fs.writeFileSync('qa-artifacts/auth-state.json', JSON.stringify({ cookies: [], origins: [] })); }   // XAU_AUTH=off: nothing to exchange
  else { throw new Error(`token exchange failed: HTTP ${r.status()} (is the gateway running with configs/api_token?)`); }
  // the suite starts with the collapsible 'More' panel open (its default is closed: see more.spec.ts)
  const sf = 'qa-artifacts/auth-state.json';
  const st = JSON.parse(fs.readFileSync(sf, 'utf8'));
  st.origins = [{ origin: new URL(base).origin, localStorage: [{ name: 'xau.more', value: '1' }] }];
  fs.writeFileSync(sf, JSON.stringify(st));
  await ctx.dispose();
}
