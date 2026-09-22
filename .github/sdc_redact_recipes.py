"""One-time public-demo redaction. Run only on the reviewed source fingerprint.
This does not purge Git history. No original recipe text is written to logs.
"""
from pathlib import Path
from html.parser import HTMLParser
import re, json, hashlib, copy

p = Path('index.html')
original = p.read_bytes()
blob = hashlib.sha1(b'blob ' + str(len(original)).encode() + b'\0' + original).hexdigest()
assert blob == '6fdd5ce6512f3f6be64d134ebe8b3f916144eb54', 'Source changed; review before editing'
s = original.decode('utf-8')
Q, E, D, C = '[SDC:QTE]', '[SDC:ETAPE]', '[SDC:DETAIL]', '[SDC:COUT]'
marker = re.compile(r'\[SDC:(?:QTE|ETAPE|DETAIL|COUT)\]')
# Do not match prices, temperatures, dates, recipe IDs or supplier pack codes.
measure = re.compile(r'(?<![\w$])(?:[~≈±−-]\s*)?\d+(?:[.,]\d+)?(?:\s*(?:[–—-]|à|x|×|/)\s*\d+(?:[.,]\d+)?)*\s*(?:kg|mg|gr?\b|grammes?|ml|cl|litres?|[lL]\b|oz|lbs?|portions?|pièces?|pieces?|gousses?|c\.?\s*à\s*[sc]\.?|cuillères?)(?!\w)', re.I)

def qty(text):
    return measure.sub(Q, str(text))

def get_array(text, name):
    m = re.search(r'const\s+' + re.escape(name) + r'\s*=\s*(\[)', text)
    assert m, name
    a = m.start(1)
    obj, length = json.JSONDecoder().raw_decode(text[a:])
    return a, a + length, obj

def replace_array(name, fn):
    global s
    a, b, obj = get_array(s, name)
    saved = copy.deepcopy(obj)
    fn(obj)
    s = s[:a] + json.dumps(obj, ensure_ascii=False, indent=2) + s[b:]
    return saved

removed = []

def hide(value, replacement):
    if isinstance(value,str) and len(value.strip()) >= 28:
        removed.append(value)
    return replacement

def recipes(rows):
    for r in rows:
        r['rendement'] = hide(r.get('rendement',''), Q)
        if r.get('notes'): r['notes'] = hide(r['notes'], D)
        r['cons'] = qty(r.get('cons',''))
        for i in r.get('ingredients',[]):
            i['n'] = qty(i['n'])
            if i.get('q'): i['q'] = hide(i['q'], Q)
        r['etapes'] = [hide(e,E) for e in r.get('etapes',[])]

def plats(rows):
    for r in rows:
        r['sub'] = qty(r.get('sub',''))
        r['temps'] = hide(r.get('temps',''), D)
        if r.get('notes'): r['notes'] = hide(r['notes'],D)
        for k in ['cuisson','montage','checks']:
            if k in r: r[k] = [hide(e,E) for e in r[k]]
        for i,m in enumerate(r.get('mep',[])):
            if isinstance(m,dict):
                m['item'] = qty(m.get('item',''))
                if m.get('detail'): m['detail'] = hide(m['detail'],D)
            else: r['mep'][i] = qty(m)

def points(rows):
    for r in rows:
        r['label'] = re.sub(r'\(base[^)]*\)', '(détail masqué)', r['label'])
        r['label'] = qty(r['label'])
        if 'choix' in r:
            r['choix'] = ['Option de démonstration ' + str(i+1) for i,_ in enumerate(r['choix'])]

old_recipes = replace_array('RECETTES', recipes)
old_plats = replace_array('PLATS', plats)
replace_array('A09_POINTS', points)
# Assistant must not hold a second, detailed cooking-method table.
a = s.index('const OS_TEMPS_RECETTES = {')
b = s.index('\n};', a) + 3
keys = re.findall(r'\b(R\d\d)\s*:', s[a:b])
s = s[:a] + 'const OS_TEMPS_RECETTES = ' + json.dumps({k:D for k in keys}, ensure_ascii=False) + ';' + s[b:]
# Isolate visitor-entered demo decisions from old cached production decisions.
s = s.replace("localStorage.getItem('coriandre_a09')", "localStorage.getItem('coriandre_a09_public_demo_v1')")
s = s.replace("localStorage.setItem('coriandre_a09',", "localStorage.setItem('coriandre_a09_public_demo_v1',")
# Exact identified secondary exposure in stock labels; quantities in actual stock remain usable.
s = s.replace("Grillade de Valleyfield — portions 150 g", "Grillade de Valleyfield — portions [SDC:QTE]")

# Source-preserving HTML parser: only protected text spans are rewritten, not the DOM layout.
class Node:
    def __init__(self,tag,attrs,start,inner,parent):
        self.tag,self.attrs,self.start,self.inner,self.parent = tag,dict(attrs),start,inner,parent
        self.end,self.close,self.children,self.data = None,None,[],[]
    def cls(self,c): return c in self.attrs.get('class','').split()
    def ancestors(self):
        n=self
        while n:
            yield n
            n=n.parent
    def inside_id(self,ids): return any(n.attrs.get('id') in ids for n in self.ancestors())
    def text(self): return ''.join(x[2] for x in self.data) + ''.join(c.text() for c in self.children)
    def descendants(self):
        for c in self.children:
            yield c
            yield from c.descendants()

class Scan(HTMLParser):
    def __init__(self,text):
        super().__init__(convert_charrefs=False)
        self.textsource=text
        self.offsets=[0]+[m.end() for m in re.finditer('\n',text)]
        self.stack=[];self.nodes=[];self.parts=[]
        self.feed(text)
    def pos(self):
        line,col=self.getpos();return self.offsets[line-1]+col
    def handle_starttag(self,tag,attrs):
        start=self.pos();inner=start+len(self.get_starttag_text())
        node=Node(tag,attrs,start,inner,self.stack[-1] if self.stack else None)
        if node.parent: node.parent.children.append(node)
        self.nodes.append(node)
        if tag not in {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}: self.stack.append(node)
        else: node.close=inner;node.end=inner
    def handle_endtag(self,tag):
        at=self.pos()
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i].tag==tag:
                node=self.stack[i];node.close=at;node.end=self.textsource.index('>',at)+1
                self.stack=self.stack[:i];break
    def handle_data(self,data):
        if not self.stack:return
        rec=(self.pos(),self.pos()+len(data),data,self.stack[-1])
        self.parts.append(rec);self.stack[-1].data.append(rec)

scan=Scan(s)
patches=[]
sensitive_sections={'sec-cuisinier-taches','sec-cuisinier-production','sec-cuisinier-recettes','sec-cuisinier-assemblage','sec-cuisinier-mep'}
fc_a=s.index('Le détail, ligne par ligne')
fc_b=s.index('Les articles qui décident du coût',fc_a)
# Hide component costs as well: supplier unit price / component cost can reveal its weight.
for node in scan.nodes:
    if not(node.cls('info-row') and fc_a<node.start<fc_b):continue
    labels=[n for n in node.descendants() if n.cls('info-label')]
    vals=[n for n in node.descendants() if n.cls('info-val')]
    if not labels or not vals:continue
    label=labels[0].text().strip()
    if re.search(r'coût théorique|coût réel|pertes|casse|repas',label,re.I):continue
    for v in vals:
        if v.close is not None: patches.append((v.inner,v.close,C))
# Steps are retained structurally, with no recipe procedure behind the blur.
for a,b,text,node in scan.parts:
    if any(n.tag in {'script','style'} for n in node.ancestors()):continue
    protected=node.inside_id(sensitive_sections) or fc_a<a<fc_b
    if not protected:continue
    new=qty(text)
    if any(n.cls('step-list') for n in node.ancestors()) and text.strip():new=E
    if new!=text:patches.append((a,b,new))
# Remove quantitative hints embedded in option labels/values from the A09 forms.
for node in scan.nodes:
    if node.tag=='option' and node.inside_id({'sec-cuisinier-production'}) and measure.search(node.text()):
        if node.close is not None:patches.append((node.inner,node.close,'Option de démonstration'))
        raw=s[node.start:node.inner]
        for key in ['value','title','aria-label']:
            raw=re.sub(r'('+key+r'=")[^"]*(")',r'\1Option de démonstration\2',raw)
        if raw!=s[node.start:node.inner]:patches.append((node.start,node.inner,raw))
# Prefer enclosing redactions, reject partial overlaps.
chosen=[]
for a,b,t in sorted(patches,key=lambda x:(x[0],-x[1])):
    if chosen and a<chosen[-1][1]:
        assert b<=chosen[-1][1], 'Unexpected overlapping HTML edit'
        continue
    chosen.append((a,b,t))
for a,b,t in reversed(chosen):s=s[:a]+t+s[b:]

# A visible, compact disclosure; same screens, no overlay that blocks navigation.
note='<div class="sdc-recipe-note">Démo publique · grammages et étapes volontairement masqués. Ces fiches ne sont pas destinées à la production.</div>'
for sid in ['sec-cuisinier-recettes','sec-cuisinier-assemblage']:
    mark='<div class="section" id="'+sid+'">'
    assert mark in s
    s=s.replace(mark,mark+'\n'+note,1)
# Keep financial demonstration honest when detail is deliberately withheld.
s=s.replace("Aucun chiffre n'est saisi à la main :", "Les grammages et le détail par ingrédient sont masqués dans cette démo :")
s=s.replace('changez un prix fournisseur, tout se recalcule.', 'les indicateurs de démonstration restent consultables.')

presentation=r'''
<!-- SDC public recipe redaction: neutral placeholders only; no hidden recipe values. -->
<style id="sdc-recipe-redaction-style">
.sdc-recipe-note{padding:9px 12px;margin:0 0 12px;border-left:2px solid #8B5CF6;background:rgba(139,92,246,.065);color:#c4bbd6;font-size:11px;line-height:1.5;}
.sdc-recipe-mask{display:inline-block;position:relative;vertical-align:baseline;min-width:4.5em;max-width:100%;line-height:1.5;user-select:none;-webkit-user-select:none;}
.sdc-recipe-mask::before{content:'000 000 000';display:inline-block;filter:blur(4px);opacity:.65;letter-spacing:.05em;color:currentColor;}
.sdc-recipe-mask[data-kind="ETAPE"]{display:block;width:min(100%,34em);min-height:2.3em;}
.sdc-recipe-mask[data-kind="ETAPE"]::before{content:'Préparation et technique réservées à la cuisine.';max-width:100%;line-height:1.8;}
.sdc-recipe-mask[data-kind="DETAIL"]::before{content:'Détail de préparation réservé';}
.sdc-recipe-mask[data-kind="COUT"]::before{content:'00,00 $';}
@media print{.sdc-recipe-mask::before{content:'[Donnée masquée — démo]'!important;filter:none!important;opacity:1!important;color:#333!important;letter-spacing:0!important;}}
</style>
<script id="sdc-recipe-redaction-ui">
(function(){
  'use strict';
  var pattern=/\[SDC:(QTE|ETAPE|DETAIL|COUT)\]/g;
  var labels={QTE:'Quantité masquée dans la démo',ETAPE:'Étape masquée dans la démo',DETAIL:'Détail masqué dans la démo',COUT:'Coût par ingrédient masqué dans la démo'};
  function convert(root){
    if(!root)return;
    var list=[];
    if(root.nodeType===3)list=[root];
    else if(root.nodeType===1){
      if(root.matches('script,style,textarea,input,option,.sdc-recipe-mask'))return;
      var w=document.createTreeWalker(root,NodeFilter.SHOW_TEXT),n;
      while((n=w.nextNode()))list.push(n);
    }
    list.forEach(function(n){
      var parent=n.parentElement;
      if(!parent||parent.closest('script,style,textarea,input,option,.sdc-recipe-mask'))return;
      var value=n.nodeValue;pattern.lastIndex=0;
      if(!pattern.test(value))return;
      pattern.lastIndex=0;
      var f=document.createDocumentFragment(),last=0,m;
      while((m=pattern.exec(value))){
        f.appendChild(document.createTextNode(value.slice(last,m.index)));
        var span=document.createElement('span');span.className='sdc-recipe-mask';
        span.dataset.kind=m[1];span.setAttribute('role','img');
        span.setAttribute('aria-label',labels[m[1]]);span.title=labels[m[1]];
        f.appendChild(span);last=m.index+m[0].length;
      }
      f.appendChild(document.createTextNode(value.slice(last)));
      parent.replaceChild(f,n);
    });
  }
  function boot(){
    convert(document.body);
    new MutationObserver(function(records){records.forEach(function(r){
      if(r.type==='characterData')convert(r.target);
      else r.addedNodes.forEach(convert);
    });}).observe(document.body,{childList:true,subtree:true,characterData:true});
    window.addEventListener('beforeprint',function(){convert(document.body);});
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
</script>
'''
assert s.count('</body>')==1
s=s.replace('</body>',presentation+'\n</body>')
# Existing tracking and financial/catalogue data must remain byte-for-byte identical.
for name in ['GFS_CATALOGUE','MENU_ENG']:
    a,b,_=get_array(original.decode(),name);oa,ob,_=get_array(s,name)
    assert original.decode()[a:b]==s[oa:ob], name+' unexpectedly changed'
old_gc=original.decode().split('<!-- SDC GoatCounter')[1].split('<!-- /SDC GoatCounter -->')[0]
assert old_gc==s.split('<!-- SDC GoatCounter')[1].split('<!-- /SDC GoatCounter -->')[0]
assert s.count('data-goatcounter=')==1
_,_,new_r=get_array(s,'RECETTES');_,_,new_p=get_array(s,'PLATS')
assert len(new_r)==22 and len(new_p)==15
for r in new_r:
    assert all(i.get('q') in ['',Q,None] for i in r['ingredients'])
    assert set(r['etapes']) <= {E}
# Check for original long method strings leaking outside the named safety module.
check=s
sa=check.index('<div class="section" id="sec-cuisinier-mapaq">')
sb=check.index('<div class="section"',sa+30)
check=check[:sa]+check[sb:]
leaks=[]
for text in removed:
    if len(text)>=55 and (text in check or json.dumps(text,ensure_ascii=True)[1:-1] in check):leaks.append(hashlib.sha256(text.encode()).hexdigest()[:10])
assert not leaks, 'Recipe strings remain outside safety module (fingerprints only): '+str(leaks)
p.write_text(s,encoding='utf-8')
print(json.dumps({'recipes':len(new_r),'assemblies':len(new_p),'source_text_edits':len(chosen),'placeholder_count':len(marker.findall(s)),'goatcounter_preserved':True,'financial_and_catalogue_data_preserved':True}))
