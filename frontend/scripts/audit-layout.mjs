/**
 * Layout regression audit: no page may be wider than the viewport.
 *
 *   npx next build && npx next start -p 3123
 *   node scripts/audit-layout.mjs
 *
 * Checks document.documentElement.scrollWidth === clientWidth on every page at
 * every width we support, and reports console errors and 404s while it is
 * there. Written after /scanner was found 30px too wide at 512px - a number
 * nobody spots by eye but that clips text on the right on a real phone.
 *
 * Point it at a FRESHLY started server. A `next start` left over from an
 * earlier build serves stale HTML and will report a fixed page as broken or a
 * broken one as fixed - both happened while this was written.
 */
import { chromium } from 'playwright';
const PAGES=['/','/scanner','/radar','/sectors','/watchlist','/forward','/backtest','/learning','/research','/data','/settings'];
const WIDTHS=[320,375,414,512,768,1280];
const b=await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
const errs=[];
const ctx=await b.newContext();
const page=await ctx.newPage();
page.on('console',m=>{ if(m.type()==='error') errs.push(`${page.url()} :: ${m.text().slice(0,120)}`); });
page.on('requestfailed',r=>errs.push(`REQFAIL ${r.url().slice(0,100)}`));
page.on('response',r=>{ if(r.status()===404) errs.push(`404 ${r.url().slice(0,100)}`); });
let bad=0;
console.log('page'.padEnd(12)+WIDTHS.map(w=>String(w).padStart(9)).join(''));
for(const p of PAGES){
  const row=[];
  for(const w of WIDTHS){
    await page.setViewportSize({width:w,height:900});
    try{ await page.goto('http://127.0.0.1:3123'+p,{waitUntil:'networkidle',timeout:25000}); }
    catch{ await page.waitForTimeout(1500); }
    await page.waitForTimeout(400);
    const m=await page.evaluate(()=>({s:document.documentElement.scrollWidth,c:document.documentElement.clientWidth}));
    const d=m.s-m.c;
    if(d>0){bad++;row.push(('+'+d).padStart(9));}else row.push('ok'.padStart(9));
  }
  console.log(p.padEnd(12)+row.join(''));
}
console.log(`\noverflowing combinations: ${bad} of ${PAGES.length*WIDTHS.length}`);
const uniq=[...new Set(errs)];
console.log(`console errors / 404s (${uniq.length}):`); uniq.slice(0,12).forEach(e=>console.log('  '+e));
await b.close();
// Non-zero exit so this can gate a build rather than only inform a human.
if (bad > 0) process.exitCode = 1;
