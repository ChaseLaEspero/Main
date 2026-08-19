# Trigger endpoint context extraction: 2026-08-19 v2
from pathlib import Path
import json

ROOT=Path('custom_portal_probe')
TERMS={
 'PE':['consultarMateriaBuscaAvancada','consultarPublicacaoElastic','consultarAnosMateriasPublicacoes','diarios-public','consultarDiarioOficialConsultaDTO','buscarJornalPorEdicao','serverUrl','vm.filtro=','intervaloAno','/public/search','consultarDatasDisponiveis'],
 'AL':['editions/published','apinova/api','search','publication_date','published?page','inputPeriodoInicial'],
 'PI':['listardiarios.json','Api/listardiarios','dataInicio','dataFim','listarDiarios'],
 'TO':['pesquisar','buscar','diario','api'],
 'RO':['api','diario','jornal','pesquisa'],
 'RR':['api','diario','pesquisa'],
}
out={}
for st,terms in TERMS.items():
 rows=[]
 for p in sorted(ROOT.glob(f'{st}_script_*.txt')):
  text=p.read_text(encoding='utf-8',errors='ignore')
  for term in terms:
   start=0;n=0
   while True:
    i=text.find(term,start)
    if i<0:break
    rows.append({'file':p.name,'term':term,'offset':i,'context':text[max(0,i-1200):min(len(text),i+2200)]})
    n+=1
    if n>=30:break
    start=i+len(term)
 out[st]=rows
Path('custom_portal_probe/endpoint_contexts.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
for st,rows in out.items():
 Path(f'custom_portal_probe/{st}_contexts.txt').write_text('\n\n=====\n\n'.join(f"FILE={r['file']} TERM={r['term']} OFFSET={r['offset']}\n{r['context']}" for r in rows),encoding='utf-8')
 print(st,len(rows))
