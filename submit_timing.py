# -*- coding: utf-8 -*-
"""How long does the submit actually take, and where?"""
import json, re, time, urllib.parse, urllib.request, http.cookiejar
BASE='http://127.0.0.1:8099'; UA={'User-Agent':'Mozilla/5.0','Accept':'text/html'}
adm=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
adm.open(urllib.request.Request(BASE+'/web/session/authenticate',
  json.dumps({'jsonrpc':'2.0','method':'call','params':{'db':'yoleyva_fitness_v2',
  'login':'yoleyva@gmail.com','password':'admin'}}).encode(),{'Content-Type':'application/json'}),timeout=30)
def kw(m,me,a,k=None):
    d=json.loads(adm.open(urllib.request.Request(BASE+'/web/dataset/call_kw',
      json.dumps({'jsonrpc':'2.0','method':'call','params':{'model':m,'method':me,'args':a,'kwargs':k or {}}}).encode(),
      {'Content-Type':'application/json'}),timeout=120).read().decode())
    if 'error' in d: raise RuntimeError(str(d['error'])[:150])
    return d['result']

for i in range(2):
    em='timing%d@yoleyva.test'%i
    old=kw('fitness.trial.request','search',[[('email','=',em)]])
    if old: kw('fitness.trial.request','unlink',[old])
    jar=http.cookiejar.CookieJar()
    op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    t0=time.time()
    h=op.open(urllib.request.Request(BASE+'/trial',headers=UA),timeout=60).read().decode('utf-8','replace')
    t_form=time.time()-t0
    tok=re.search(r'name="csrf_token"\s+value="([^"]+)"',h).group(1)
    sl=re.findall(r'name="occurrence_id"[^>]*id="rslot_(\d+)"', h)[0]
    hh=dict(UA); hh['Referer']=BASE+'/trial'; hh['Content-Type']='application/x-www-form-urlencoded'
    t1=time.time()
    op.open(urllib.request.Request(BASE+'/trial/submit', urllib.parse.urlencode({
      'csrf_token':tok,'name':'Timing','email':em,'class_interest':'reformer',
      'occurrence_id':sl}).encode(), headers=hh),timeout=120).read()
    t_submit=time.time()-t1
    print('run %d:  form %.2fs   submit %.2fs' % (i+1, t_form, t_submit))
    ids=kw('fitness.trial.request','search',[[('email','=',em)]])
    if ids: kw('fitness.trial.request','unlink',[ids])
