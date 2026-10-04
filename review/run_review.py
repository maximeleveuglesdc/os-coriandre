"""Five-point Coriandre review. No deployment, email, contact or analytics writes."""
import asyncio, base64, hashlib, json, re, subprocess, threading, zlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from playwright.async_api import async_playwright

BASE = 'https://raw.githubusercontent.com/maximeleveuglesdc/os-coriandre/'
SOURCE = '47d2c98ae44d26888bed1e8ab6a5e5a0cb6b8f17'
SOURCE_HASH = 'cc7f2c85a357cfb3239900c9e19c1077146dcba87517600d20b5ca4ff955a43c'
TARGET_HASH = 'a760702ccd1a97ac4bf6872bf942ac2e312dee30eee7e3680e20acd563eefc0c'
BRANCH = 'audit/cinq-points-20261004'
OUT = Path('review-output'); OUT.mkdir(exist_ok=True)

def get(url):
    with urlopen(Request(url, headers={'User-Agent':'SDC-review/1.0','Cache-Control':'no-cache'}), timeout=30) as r:
        return r.read()

def sha(data): return hashlib.sha256(data).hexdigest()
original = get(BASE + SOURCE + '/index.html')
assert sha(original) == SOURCE_HASH
encoded = get(BASE + BRANCH + '/review/cinq-points.patch.zlib.b64').decode().strip()
# Normalize four transport transcription errors; digest guards the exact original patch.
for old, new in [('PPVyPVyPFl','PPVyPFl'),('JvSL6stVf','JvSLF6stVf'),('Lq0U1klAm','Lq0D1klAm'),('KoMyyWqvNiT','KoMyqWqvNiT')]:
    encoded = encoded.replace(old,new)
assert sha(encoded.encode()) == 'bd41182db8949881ef46ce4b7f17f2b1768fb329de3fbb499a904e6aba109ed9', 'Patch transport differs'
changes = json.loads(zlib.decompress(base64.b64decode(encoded)))
text = original.decode()
for change in changes:
    assert text.count(change['avant']) == change['occurrences'], change['point']
    text = text.replace(change['avant'],change['apres'])
candidate = text.encode()
assert sha(candidate) == TARGET_HASH
(OUT/'index-before.html').write_bytes(original)
(OUT/'index.html').write_bytes(candidate)
(OUT/'modifications.json').write_text(json.dumps(changes,ensure_ascii=False,indent=2))
checks = {'original_sha256':SOURCE_HASH,'candidate_sha256':TARGET_HASH,'source_commit':SOURCE,'published':False,'items':[],'pages':[],'interception_used_for_main_site':True}

def test(name, condition, **details):
    item={'name':name,'ok':bool(condition),**details};checks['items'].append(item);print(json.dumps(item,ensure_ascii=False),flush=True)
    return bool(condition)

style = lambda s: re.findall(r'<style\b[^>]*>(.*?)</style>',s,re.S)
imgs = lambda s: re.findall(r'data:image/[^\s\"\x27<>]+',s)
mask = lambda s: re.findall(r'\[SDC:[^\]]+\]',s)
test('CSS unchanged',style(text)==style(original.decode()))
test('Embedded images unchanged',imgs(text)==imgs(original.decode()))
test('Masked tokens unchanged',mask(text)==mask(original.decode()))
blocks = re.findall(r'<script\b([^>]*)>(.*?)</script>',text,re.S)
syntax=[]
for i,(attrs,code) in enumerate(blocks):
    if not code.strip() or 'application/' in attrs:continue
    p=OUT/f'script-{i}.js';p.write_text(code)
    r=subprocess.run(['node','--check',str(p)],capture_output=True,text=True)
    syntax.append({'block':i,'ok':r.returncode==0,'error':r.stderr[:800]})
test('Inline script syntax',all(x['ok'] for x in syntax),blocks=syntax)

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(OUT.resolve()),**kwargs)
    def log_message(self,*args):pass
server=ThreadingHTTPServer(('127.0.0.1',8765),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()

async def protect(route, embedded=False):
    req=route.request;u=req.url
    if embedded and req.is_navigation_request() and urlsplit(u).netloc=='coriandre.structuredecuisine.ca':
        await route.fulfill(status=200,content_type='text/html; charset=utf-8',body=candidate)
    elif req.method not in ('GET','HEAD') or any(x in u for x in ['goatcounter.com','gc.zgo.at','google-analytics.com','googletagmanager.com','connect.facebook.net','facebook.com/tr']):
        await route.abort()
    else:await route.continue_()

async def shot(page,label,full=False):
    await page.wait_for_timeout(450)
    await page.screenshot(path=str(OUT/(label+'.png')),full_page=full,animations='disabled')

async def nav(page, section):
    button=page.locator('#nav-'+section)
    if await button.count() and await button.is_visible():await button.click()
    else:
        more=page.locator('#nav-more')
        if await more.count() and await more.is_visible():
            await more.click()
            row=page.locator('#nav-more-sheet button').filter(has=page.locator('span'))
            target=page.locator('#nav-more-sheet button[onclick*="'+section+'"]')
            if await target.count():await target.click()
            else:await page.evaluate('(id)=>{closeMoreNav();showSection(id)}',section)
        else:await page.evaluate('(id)=>showSection(id)',section)
    await page.wait_for_timeout(260)
    return await page.locator('#'+section).evaluate('(e)=>e.classList.contains("active")')

async def inspect(browser, label, path, width=1440):
    context=await browser.new_context(viewport={'width':width,'height':1000 if width>700 else 844},device_scale_factor=1)
    await context.route('**/*',protect)
    page=await context.new_page();errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    record={'label':label,'width':width,'roles':[]}
    try:
        await page.goto('http://127.0.0.1:8765/'+path,wait_until='domcontentloaded')
        await page.wait_for_timeout(1500)
        await shot(page,label+'-entree')
        data=await page.evaluate('''() => ({recipes:RECETTES.map(r=>r.id),plats:PLATS.map(p=>p.num),catalogue:GFS_CATALOGUE.length,menu:MENU_ENG.length,gate:getComputedStyle(document.querySelector('#gate-admin')).display})''')
        test(label+' data counts',data['catalogue']==134 and len(data['recipes'])==22 and len(data['plats'])==15,**data)
        for role in ['cuisinier','admin']:
            await page.locator('.role-card.'+role).click()
            await page.wait_for_timeout(650)
            test(label+' '+role+' entry',await page.locator('#main-app').is_visible() and not await page.locator('#gate-admin').is_visible())
            ids=await page.evaluate('(role)=>(role==="admin"?NAV_ADMIN:NAV_CUISINIER).map(x=>x.id)',role)
            visits=[]
            for sid in ids:
                ok=await nav(page,sid);visits.append({'section':sid,'active':ok})
            test(label+' '+role+' navigation',all(x['active'] for x in visits),sections=visits)
            for rid in data['recipes']:
                await page.evaluate('(id)=>openRecette(id)',rid)
                title=await page.locator('#modal-recette-title').inner_text()
                test(label+' '+role+' recipe '+rid,rid in title and await page.locator('#modal-recette').is_visible())
                await page.locator('#modal-recette .modal-close').click()
            for pid in data['plats']:
                await page.evaluate('(id)=>openPlat(id)',pid)
                test(label+' '+role+' assembly '+pid,await page.locator('#modal-plat').is_visible())
                await page.locator('#modal-plat .modal-close').click()
            await nav(page,'sec-'+role+'-commande')
            await page.locator('[onclick="updateGFSQty(\''+role+'\',\'G45\',1)"]').click()
            qty=await page.locator('#qty-'+role+'-G45').inner_text()
            line=await page.locator('#line-'+role+'-G45').inner_text()
            test(label+' '+role+' cart',qty=='1' and '22.99' in line,quantity=qty,total=line)
            await page.locator('[onclick="updateGFSQty(\''+role+'\',\'G45\',-1)"]').click()
            await page.evaluate('openSearch()')
            await page.locator('#search-input').fill('houmous')
            test(label+' '+role+' search',len(await page.locator('#search-results').inner_text())>10)
            await page.locator('#search-overlay .modal-close').click()
            if role=='cuisinier':
                await nav(page,'sec-cuisinier-recettes')
                await page.locator('#search-recettes-cui').fill('houmous')
                btn=page.locator('#recettes-list [onclick^="openRecette("]').first
                await btn.click();await shot(page,label+'-recette')
                await page.emulate_media(media='print')
                print_data=await page.locator('#modal-recette-body').inner_text()
                test(label+' print recipe visible',len(print_data)>100)
                await page.emulate_media(media='screen')
                await page.locator('#modal-recette .modal-close').click()
                await nav(page,'sec-cuisinier-mapaq')
                if label.startswith('after'):
                    await page.locator('#sdc-mapaq-sources summary').click()
                    nlinks=await page.locator('#sdc-mapaq-sources a[href^="https://www.quebec.ca/"]').count()
                    test(label+' official MAPAQ links',nlinks>=7,links=nlinks)
                    await page.locator('#sdc-mapaq-sources').scroll_into_view_if_needed()
                await shot(page,label+'-mapaq')
                await page.evaluate('openIA()')
                await page.locator('#ia-input').fill('MAPAQ')
                await page.locator('#ia-input').press('Enter')
                await page.wait_for_timeout(800)
                answer=await page.locator('#ia-messages').inner_text()
                test(label+' assistant MAPAQ',len(answer)>100,excerpt=answer[-700:])
                await page.locator('.ia-close').click()
            else:
                await nav(page,'sec-admin-foodcost')
                await shot(page,label+'-foodcost')
                txt=await page.locator('#sec-admin-foodcost').inner_text()
                if label.startswith('after'):test(label+' hypothesis label','hypothèse' in txt.lower() and '1,07' in txt)
                await nav(page,'sec-admin-achats')
                await page.locator('#v2-price-search').fill('G45')
                test(label+' pricelist filter',await page.locator('#v2-price-body tr').count()==1)
                if label.startswith('after'):test(label+' sourced price link',await page.locator('#v2-price-body a').count()>0)
                await page.locator('#v2-price-search').fill('')
                await page.locator('#v2-tab-inventory').click()
                test(label+' inventory',await page.locator('#v2-inv-body tr').count()==8)
                await page.locator('#v2-tab-pricelist').click()
                if label.startswith('after'):
                    await page.locator('#sdc-provenance summary').click()
                    await page.locator('#sdc-provenance').scroll_into_view_if_needed()
                await shot(page,label+'-provenance')
            record['roles'].append({'role':role,'navigation_count':len(ids),'recipes':len(data['recipes']),'assemblies':len(data['plats'])})
            await page.evaluate('switchRole()');await page.wait_for_timeout(400)
    except Exception as e:
        record['test_exception']=str(e);test(label+' completion',False,error=str(e))
        await shot(page,label+'-failure')
    record['page_errors']=errors
    test(label+' no JS page errors',not errors,errors=errors)
    checks['pages'].append(record)
    await context.close()

async def embedded(browser,path,width):
    label='embedded-'+('restaurant' if path else 'home')+'-'+str(width)
    context=await browser.new_context(viewport={'width':width,'height':1000 if width>700 else 844})
    await context.route('**/*',lambda route:protect(route,True))
    page=await context.new_page();errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    record={'label':label,'live_parent':'https://structuredecuisine.ca/'+path,'candidate_iframe_intercepted':True}
    try:
        await page.goto(record['live_parent'],wait_until='domcontentloaded',timeout=45000)
        await page.locator('.coriandre-launcher').click(timeout=20000)
        frame=page.frame_locator('.coriandre-floating-panel iframe')
        await frame.locator('.role-card.admin').click(timeout=20000)
        test(label+' manager iframe',await frame.locator('#main-app').is_visible())
        await page.get_by_role('button',name='Agrandir la fenêtre',exact=True).click()
        await shot(page,label+'-gestion')
        await page.get_by_role('button',name='Pause',exact=True).click()
        test(label+' pause button',await page.get_by_role('button',name='Reprendre',exact=True).is_visible())
        await page.get_by_role('button',name='Reprendre',exact=True).click()
        await page.get_by_role('button',name='Agrandir le zoom',exact=True).click()
        test(label+' zoom', '110' in await page.get_by_role('button',name='Réinitialiser le zoom à 100 %',exact=True).inner_text())
        await page.get_by_role('button',name='Réinitialiser le zoom à 100 %',exact=True).click()
        await frame.locator('[onclick="switchRole()"]').click()
        await frame.locator('.role-card.cuisinier').click()
        test(label+' kitchen iframe',await frame.locator('#main-app').is_visible())
        await shot(page,label+'-cuisine')
        links=await page.locator('.coriandre-floating-panel a[href*="coriandre.structuredecuisine.ca"]').count()
        test(label+' open separate demo link',links>0)
        await page.get_by_role('button',name='Fermer la démonstration',exact=True).click()
        test(label+' close panel',await page.locator('.coriandre-floating-panel').count()==0)
    except Exception as e:
        record['test_exception']=str(e);test(label+' completion',False,error=str(e));await shot(page,label+'-failure')
    record['page_errors']=errors;checks['pages'].append(record)
    await context.close()

async def main():
    async with async_playwright() as pw:
        browser=await pw.chromium.launch()
        for label,path,width in [('before-desktop','index-before.html',1440),('after-desktop','index.html',1440),('after-mobile','index.html',390)]:
            await inspect(browser,label,path,width)
        for path,width in [('',1440),('restaurant',1440),('',390)]:await embedded(browser,path,width)
        await browser.close()
try:asyncio.run(main())
finally:
    checks['all_assertions_passed']=all(x['ok'] for x in checks['items'])
    (OUT/'browser-checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2))
    server.shutdown()
    print('REVIEW_ONLY_NO_PUBLICATION')
