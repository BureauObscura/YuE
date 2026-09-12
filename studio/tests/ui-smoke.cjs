// Run against an isolated --data-dir. Requires Playwright and local Chrome.
// No music model or paid image provider is used by this test.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.STUDIO_TEST_URL || 'http://127.0.0.1:8766';
const output = process.env.STUDIO_TEST_OUTPUT || '/private/tmp/yue-studio-ui-results';
fs.mkdirSync(output, {recursive:true});
function wav(){const rate=24000, samples=rate*3;const data=Buffer.alloc(44+samples*2);data.write('RIFF');data.writeUInt32LE(data.length-8,4);data.write('WAVE',8);data.write('fmt ',12);data.writeUInt32LE(16,16);data.writeUInt16LE(1,20);data.writeUInt16LE(1,22);data.writeUInt32LE(rate,24);data.writeUInt32LE(rate*2,28);data.writeUInt16LE(2,32);data.writeUInt16LE(16,34);data.write('data',36);data.writeUInt32LE(samples*2,40);for(let i=0;i<samples;i++)data.writeInt16LE(Math.round(Math.sin(i*2*Math.PI*220/rate)*1500),44+i*2);return data;}
async function until(fn){for(let i=0;i<100;i++){const value=await fn();if(value)return value;await new Promise(r=>setTimeout(r,100));}throw new Error('Condition timed out');}
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
 const page=await browser.newPage({viewport:{width:1360,height:1000},deviceScaleFactor:1});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const state=async()=> (await page.request.get(base+'/api/bootstrap')).json();
 const name='Midnight window · interface test '+Date.now();let track;
 try {
  await page.goto(base);await page.getByRole('heading',{name:'A new composition',exact:true}).waitFor();
  await page.screenshot({path:path.join(output,'01-composer.png'),fullPage:true});
  await page.getByLabel('Song title',{exact:true}).fill(name);
  await page.getByLabel('Artist name',{exact:true}).fill('UI validation');
  await page.getByLabel('Song lyrics',{exact:true}).fill('[Verse]\nThis is a test fixture.\n\n[Chorus]\nNo generated song is claimed.');
  await page.getByRole('button',{name:'Ambient',exact:true}).click();
  track=await until(async()=> (await state()).tracks.find(t=>t.title===name&&t.style.includes('ambient')&&t.lyrics.includes('test fixture')));
  assert.equal(track.takes.length,0);
  await page.locator('input[type=file]').nth(0).setInputFiles({name:'test-tone.wav',mimeType:'audio/wav',buffer:wav()});
  track=await until(async()=>{const t=(await state()).tracks.find(t=>t.id===track.id);return t?.takes.some(t=>t.audio_url)?t:null;});
  assert.equal(track.takes.length,1);assert.equal(track.takes[0].status,'complete');
  await page.getByRole('button',{name:'Play',exact:true}).click();
  await until(()=>page.locator('audio').evaluate(a=>a.currentTime>.2));
  await page.getByRole('button',{name:'Pause',exact:true}).click();
  const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=','base64');
  await page.locator('input[type=file]').nth(1).setInputFiles({name:'test-cover.png',mimeType:'image/png',buffer:png});
  track=await until(async()=>{const t=(await state()).tracks.find(t=>t.id===track.id);return t?.cover_url?t:null;});
  const downloadPromise=page.waitForEvent('download');await page.getByRole('link',{name:'Export selected take & artwork'}).click();const download=await downloadPromise;await download.saveAs(path.join(output,'test-export.zip'));
  await page.getByRole('button',{name:'Generate take',exact:true}).first().click();await page.getByRole('dialog',{name:'Music engine'}).waitFor();
  assert.match(await page.getByRole('dialog').innerText(),/Setup required/);
  assert.equal((await state()).tracks.find(t=>t.id===track.id).takes.length,1);
  await page.screenshot({path:path.join(output,'02-engine.png')});await page.getByRole('button',{name:'Close dialog'}).click();
  await page.getByRole('button',{name:'Create another',exact:true}).click();await page.getByRole('dialog',{name:'Create cover artwork'}).waitFor();
  assert.equal(await page.getByRole('button',{name:'Generate cover',exact:true}).isDisabled(),true);
  await page.getByRole('button',{name:'Close dialog'}).click();
  await page.getByRole('button',{name:/^Library/}).click();await page.getByLabel('Search library').fill(name);
  await page.getByRole('button',{name:'Favorite composition',exact:true}).click();
  await until(async()=> (await state()).tracks.find(t=>t.id===track.id)?.favorite);
  await page.getByRole('button',{name:'Favorites',exact:true}).click();
  await page.locator('article').getByRole('button',{name:name,exact:true}).click();await page.getByLabel('Song title').waitFor();
  await page.getByLabel('Song lyrics',{exact:true}).fill('[Verse]\nAn edited draft after the recording.');
  await until(async()=> (await state()).tracks.find(t=>t.id===track.id)?.lyrics.includes('edited draft'));
  await page.reload();await page.getByRole('heading',{name:'A new composition',exact:true}).waitFor();
  const persisted=(await state()).tracks.find(t=>t.id===track.id);assert.equal(persisted.favorite,true);assert.ok(persisted.cover_url);assert.equal(persisted.takes.length,1);assert.ok(persisted.lyrics.includes('edited draft'));
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'mobile overflow');
  await page.screenshot({path:path.join(output,'03-mobile.png'),fullPage:true});
  const csrf=(await state()).csrf;const deleted=await page.request.delete(`${base}/api/tracks/${track.id}`,{headers:{'X-Studio-Token':csrf}});assert.equal(deleted.status(),200);track=null;
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({passed:true,checks:['draft autosave','audio import','real playback','cover upload','ZIP export','missing engine state','paid artwork disabled without key','library search','favorites','reload persistence','mobile overflow','no page errors'],output}));
 } finally {
  if(track){const s=await state();await page.request.delete(`${base}/api/tracks/${track.id}`,{headers:{'X-Studio-Token':s.csrf}}).catch(()=>{});}
  await browser.close();
 }
})().catch(e=>{console.error(e);process.exit(1);});
