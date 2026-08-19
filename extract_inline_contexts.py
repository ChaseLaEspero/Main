from pathlib import Path
import json

ROOT=Path('remaining_portals_diag')
TERMS={
 'PI':['listardiarios','Api/','ajax','serverSide','dataInicio','dataFim','dtInicio','dtFim'],
 'TO':['ajax','api','buscar','pesquisar','diario','download'],
 'RO':['ajax','api','buscar','pesquisar','diario','download'],
 'RR':['ajax','api','buscar','pesquisar','diario','download'],
 'MA':['ajax','api','buscar','pesquisar','diario','download'],
 'SE':['ajax','api','buscar','pesquisar','diario','download'],
 'AC':['download.php','ajax','pesquisa','dataInicio','dataFim'],
 'DF':['api','consulta','pesquisa','download'],
}
for st,terms in TERMS.items():
 p=ROOT/f'{st}_page.html'
 if not p.exists():continue
 text=p.read_text(encoding='utf-8',errors='ignore')
 rows=[]
 for term in terms:
  start=0;n=0
  while True:
   i=text.find(term,start)
   if i<0:break
   rows.append({'term':term,'offset':i,'context':text[max(0,i-1800):min(len(text),i+3000)]})
   n+=1
   if n>=30:break
   start=i+len(term)
 Path(ROOT/f'{st}_inline_contexts.txt').write_text('\n\n=====\n\n'.join(f"TERM={r['term']} OFFSET={r['offset']}\n{r['context']}" for r in rows),encoding='utf-8')
 print(st,len(rows))
