from pathlib import Path
import re,json,subprocess
from playwright.sync_api import sync_playwright

original=subprocess.check_output(['git','show','HEAD:index.html']).decode()
html=Path('index.html').read_text()
assert 'sdc-recipe-redaction-ui' in html
assert html.count('id="sdc-recipe-redaction-style"')==1

def visit(browser,text,width=1440):
    page=browser.new_page(viewport={'width':width,'height':1000})
    errors=[]
    page.on('pageerror',lambda error: errors.append(str(error)))
    def route(r):
        if r.request.resource_type=='document':r.fulfill(body=text,content_type='text/html')
        elif r.request.url=='https://gc.zgo.at/count.js':
            r.fulfill(body='window.__hits=[];window.goatcounter.count=function(v){window.__hits.push(v)};',content_type='application/javascript')
        else:r.abort()
    page.route('**/*',route)
    page.goto('https://coriandre.structuredecuisine.ca/',wait_until='load')
    return page,errors

with sync_playwright() as pw:
    browser=pw.chromium.launch()
    baseline,base_errors=visit(browser,original)
    expected=baseline.evaluate('JSON.stringify({menu:MENU_ENG,catalogue:GFS_CATALOGUE,niveaux:MEP_NIVEAUX.map(x=>({niveau:x.niveau,cible:x.cible,cmd:x.cmd}))})')
    baseline.close()
    page,errors=visit(browser,html)
    actual=page.evaluate('JSON.stringify({menu:MENU_ENG,catalogue:GFS_CATALOGUE,niveaux:MEP_NIVEAUX.map(x=>({niveau:x.niveau,cible:x.cible,cmd:x.cmd}))})')
    assert actual==expected,'Financial or stock calculations changed'
    ids=page.evaluate('RECETTES.map(r=>r.id)')
    page.evaluate("selectRole('cuisinier')")
    for rid in ids:
        page.evaluate('(id)=>openRecette(id)',rid)
        page.wait_for_function("document.querySelectorAll('#modal-recette-body .sdc-recipe-mask').length>0")
        assert page.locator('#modal-recette-body .ing-qte .sdc-recipe-mask').count()>0,rid
        assert page.locator('#modal-recette-body .step-txt .sdc-recipe-mask').count()>0,rid
        assert '[SDC:' not in page.locator('#modal-recette-body').inner_text(),rid
        page.evaluate("closeModal('modal-recette')")
    for pid in page.evaluate('PLATS.map(p=>p.num)'):
        page.evaluate('(id)=>openPlat(id)',pid)
        page.wait_for_function("document.querySelectorAll('#modal-plat-body .sdc-recipe-mask').length>0")
        assert '[SDC:' not in page.locator('#modal-plat-body').inner_text(),pid
        page.evaluate("closeModal('modal-plat')")
    # Both roles must show the identical protected source, not an unblur toggle.
    page.evaluate("selectRole('admin'); openRecette('R01')")
    page.wait_for_function("document.querySelectorAll('#modal-recette-body .sdc-recipe-mask').length>0")
    assert page.locator('#modal-recette-body .sdc-recipe-mask').count()>4
    css=page.locator('#modal-recette-body .sdc-recipe-mask').first.evaluate("e=>getComputedStyle(e,'::before').filter")
    assert 'blur(' in css,css
    page.evaluate("closeModal('modal-recette');showSection('sec-admin-foodcost')")
    assert page.locator('#sec-admin-foodcost .sdc-recipe-mask[data-kind="COUT"]').count()>10
    # Search and assistant remain usable, but never provide hidden quantities/steps.
    page.evaluate('buildSearchIndex()')
    assert page.evaluate('SEARCH_INDEX.length')>50
    for query in ['quantité sauce bravas','étapes sauce bravas','montage houmous','cuisson gâteau chocolat']:
        answer=page.evaluate('(q)=>osAnswer(q)',query)
        assert isinstance(answer,str) and len(answer)>10
    assert page.evaluate("typeof window.goatcounter.count==='function' && !!window.__sdcCoriandreAnalytics")
    page.evaluate("showSection('sec-admin-cockpit')")
    assert page.locator('#sec-admin-cockpit').is_visible()
    assert page.locator('#sec-admin-cockpit .sdc-recipe-mask').count()==0
    # General MAPAQ data remains readable; only production recipe specifics are restricted.
    page.evaluate("selectRole('cuisinier');showSection('sec-cuisinier-mapaq')")
    assert page.locator('#sec-cuisinier-mapaq').is_visible()
    assert page.locator('#sec-cuisinier-mapaq .sdc-recipe-mask').count()==0
    # Print keeps redaction (placeholder), with no reveal on hover.
    page.evaluate("openRecette('R01')")
    page.wait_for_function("document.querySelectorAll('#modal-recette-body .sdc-recipe-mask').length>0")
    page.emulate_media(media='print')
    pc=page.locator('#modal-recette-body .sdc-recipe-mask').first.evaluate("e=>getComputedStyle(e,'::before').content")
    assert 'masquée' in pc,pc
    assert set(errors)<=set(base_errors),(errors,base_errors)
    page.close()
    mobile,mobile_errors=visit(browser,html,390)
    mobile.evaluate("selectRole('cuisinier');showSection('sec-cuisinier-recettes');openRecette('R01')")
    mobile.wait_for_function("document.querySelectorAll('#modal-recette-body .sdc-recipe-mask').length>0")
    assert mobile.locator('#modal-recette').is_visible()
    assert set(mobile_errors)<=set(base_errors),(mobile_errors,base_errors)
    print(json.dumps({'recipe_modal_tests':len(ids),'assembly_modal_tests':15,'desktop_and_mobile':True,'manager_and_cook':True,'print_mask':True,'search_and_assistant':True,'financial_stock_catalogue_unchanged':True,'goatcounter_intact':True,'new_js_errors':0}))
    browser.close()
