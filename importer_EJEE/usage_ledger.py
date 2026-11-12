"""Read actual selection usage without mixing stores or counting publish twice."""
import sqlite3

from importer_EJEE import app_service, library_store


def phases(connection, paper_id=None):
    where=' WHERE paper_id=?' if paper_id is not None else ''
    return [dict(r) for r in connection.execute(
        'SELECT phase,count(*) calls,coalesce(sum(input),0) input,coalesce(sum(cache_read),0) cached,'
        'coalesce(sum(output),0) output,coalesce(sum(reasoning),0) reasoning FROM token_usage'+where+' GROUP BY phase',
        (paper_id,) if paper_id is not None else ())]


def priced(rows):
    import config
    result=[]
    for row in rows:
        row=dict(row)
        row['cost_usd']=((row['input']-row['cached'])*config.PRICING['input_per_mtok']+
                         row['cached']*config.PRICING['cache_read_per_mtok']+
                         row['output']*config.PRICING['output_per_mtok'])/1e6
        result.append(row)
    return result


def totals(rows):
    return {**{k:sum(r[k] for r in rows) for k in ('calls','input','cached','output','reasoning','cost_usd')},
            'extraction_usd':sum(r['cost_usd'] for r in rows if r['phase']=='extractor'),
            'classification_usd':sum(r['cost_usd'] for r in rows if r['phase']=='topics')}


def selection_usage():
    target=library_store.store();entries=[];published=set();warnings=[]
    with library_store.connect() as c:
        if c.execute("SELECT 1 FROM sqlite_master WHERE name='ejee_imports'").fetchone():
            published={r[0] for r in c.execute('SELECT source_key FROM ejee_imports i JOIN papers p ON p.id=i.paper_id')}
        for paper in c.execute("SELECT p.id,p.paper_name,p.source_institute,p.status,count(q.id) questions FROM papers p LEFT JOIN questions q ON q.paper_id=p.id WHERE p.exam_type='EJEE collection' GROUP BY p.id ORDER BY p.id DESC"):
            rows=priced(phases(c,paper['id']))
            entries.append({'id':f'paper:{paper["id"]}','paper_id':paper['id'],'name':paper['paper_name'],
                'source':paper['source_institute'],'status':paper['status'],'questions':paper['questions'],
                'phases':rows,**totals(rows)})
    for job in app_service.list_jobs():
        if job.get('kind')!='selection' or job['target_db']!=str(target['db']) or job['source_key'] in published:
            continue
        db=app_service.WEB/job['id']/'paperlab.db';rows=[]
        if db.exists():
            try:
                with sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True,timeout=2) as c:
                    c.row_factory=sqlite3.Row;rows=priced(phases(c))
            except (OSError,sqlite3.Error):
                warnings.append(f'Usage for {job["chapter"]} is temporarily unavailable. Refresh to retry.')
        entries.append({'id':f'job:{job["id"]}','paper_id':None,'name':job['chapter'],'source':job['book'],
                        'status':job['status'],'questions':job['total'],'phases':rows,**totals(rows)})
    grouped={}
    for entry in entries:
        for row in entry['phases']:
            aggregate=grouped.setdefault(row['phase'],{'phase':row['phase'],**dict.fromkeys(('calls','input','cached','output','reasoning'),0)})
            for k in ('calls','input','cached','output','reasoning'):aggregate[k]+=row[k]
    breakdown=priced(grouped.values())
    return {'label':'EJEE Selection Process','separate_library':True,'estimated':True,'rows':entries,
            'phases':breakdown,'totals':totals(breakdown),'collections':len(entries),'warnings':warnings}
