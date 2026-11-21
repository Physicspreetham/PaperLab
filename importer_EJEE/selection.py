"""Filter EJEE questions using its own taxonomy; no book chapter adapter needed."""
from collections import defaultdict
import hashlib
import io
import json
from pathlib import Path

from importer_EJEE import app_service as service

QUESTION_TYPES = ('objective','subjective','jmain','jadv','olympiad','pyq')
ELIGIBLE = "coalesce(r.part,'q')='q' AND r.type IN ('objective','subjective','jmain','jadv','olympiad','pyq')"
MAX_SELECTION = 1000


def source_token():
    return hashlib.sha256(json.dumps(service.settings(),sort_keys=True).encode()).hexdigest()


def selection_key(row):
    return hashlib.sha256(json.dumps([row['source'],row['grp'] or f'resource:{row["id"]}']).encode()).hexdigest()


def values(value, *, limit=200):
    if value in (None,'',[]):return []
    result=value if isinstance(value,list) else [value]
    if (limit is not None and len(result)>limit) or any(not isinstance(v,str) or len(v)>1000 for v in result):
        raise ValueError('Invalid filter values')
    return result


def where(filters):
    clauses=[ELIGIBLE];params=[];prefix=''
    node_ids = filters.get('node_ids', [])
    if not isinstance(node_ids, list) or any(type(node) is not int or node <= 0 for node in node_ids):
        raise ValueError('Invalid subtopic selection')
    if not node_ids and filters.get('node_id'):
        node_ids = [int(filters['node_id'])]
    if node_ids:
        prefix = ('WITH RECURSIVE chosen(id) AS ('
                  'SELECT id FROM nodes WHERE id IN (SELECT value FROM json_each(?)) '
                  'UNION SELECT n.id FROM nodes n JOIN chosen p ON n.parent_id=p.id) ')
        params.append(json.dumps(list(dict.fromkeys(node_ids))))
        clauses.append('r.topic_id IN (SELECT id FROM chosen)')
    for field in ('source','qtype','type','difficulty','exam','year','status'):
        selected=values(filters.get(field), limit=None if field=='source' else 200)
        if not selected:continue
        known=[v for v in selected if v!='__none__'];parts=[]
        if known:
            if field=='source':
                parts.append('CAST(r.source AS TEXT) IN (SELECT value FROM json_each(?))')
                params.append(json.dumps(list(dict.fromkeys(known))))
            else:
                parts.append(f'CAST(r.{field} AS TEXT) IN ('+','.join('?' for _ in known)+')');params.extend(known)
        if '__none__' in selected:parts.append(f"(r.{field} IS NULL OR CAST(r.{field} AS TEXT)='')")
        clauses.append('('+' OR '.join(parts)+')')
    text=str(filters.get('q') or '').strip()
    if len(text)>250:raise ValueError('Search text is too long')
    if text:
        escaped=text.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
        clauses.append("("+' OR '.join(f"coalesce(r.{f},'') LIKE ? ESCAPE '\\'" for f in ('title','question','answer','solution','tags'))+")")
        params.extend(['%'+escaped+'%']*5)
    if filters.get('fav'):clauses.append('r.fav=1')
    if filters.get('altered'):clauses.append("coalesce(r.altered,'')<>''")
    return prefix,' AND '.join(clauses),params


def facets():
    cfg=service.settings();c=service.source_connection(cfg['source_db'])
    try:
        result={'source_token':source_token(),'nodes':[dict(r) for r in c.execute('SELECT id,parent_id,level,name,position FROM nodes ORDER BY position,id')],
                'max_selection':MAX_SELECTION}
        for field in ('source','qtype','type','difficulty','exam','year','status'):
            normalized=f"CASE WHEN r.{field} IS NULL OR CAST(r.{field} AS TEXT)='' THEN '__none__' ELSE CAST(r.{field} AS TEXT) END"
            result[field]=[{'value':r[0],'count':r[1]} for r in c.execute(f'SELECT {normalized} value,count(*) FROM resources r WHERE {ELIGIBLE} GROUP BY value ORDER BY value')]
        return result
    finally:c.close()


def node_path(nodes,node):
    parts=[];seen=set()
    while node in nodes and node not in seen:
        seen.add(node);parts.append(nodes[node]['name']);node=nodes[node]['parent_id']
    return ' › '.join(reversed(parts))


def image_issue(row,asset_root):
    if not row['file_name']:return 'Source image is missing'
    root=Path(asset_root).resolve();path=(root/row['file_name']).resolve()
    if root not in path.parents or not path.is_file():return 'Source image file is unavailable'
    if path.suffix.lower() not in ('.png','.jpg','.jpeg','.webp','.bmp','.tif','.tiff','.gif'):
        return 'This resource is not an indexed question image'
    try:
        meta=json.loads(row['print_meta'] or '{}')
        if not isinstance(meta,dict):return 'Question image crop needs review in EJEE'
        box=meta.get('box') or meta.get('qbox')
        if not box or len(box)!=4 or not (0<=box[0]<box[2]<=1 and 0<=box[1]<box[3]<=1):return 'Question image crop needs review in EJEE'
    except (ValueError,TypeError,KeyError):return 'Question image crop needs review in EJEE'
    return None


_ORDER_CACHE={}


def _natural(text):
    import re
    return [int(p) if p.isdigit() else p.casefold() for p in re.split(r'(\d+)',text or '')]


def order_key(row,nodes):
    """Syllabus order first (module, chapter, week, topic/subtopic positions); within a subtopic group by source, then card title."""
    cache=nodes.setdefault('__memo__',{})  # per-call memo of topic_id -> syllabus tuple
    topic=row['topic_id']
    if topic not in cache:
        path=[];node=topic;seen=set()
        while node in nodes and node not in seen:
            seen.add(node);path.append(nodes[node]);node=nodes[node]['parent_id']
        path.reverse()
        cache[topic]=tuple((n['position'] if n['position'] is not None else 1<<30,n['id']) for n in path)
    syllabus=cache[topic]
    source=row['source']
    return ((0,syllabus) if syllabus else (1,()),
            (1,'') if source in (None,'') else (0,str(source).casefold()),
            _natural(row['title']),row['position'] if row['position'] is not None else 0,row['id'])


def search(filters,offset=0,limit=30):
    if offset<0 or not 1<=limit<=100:raise ValueError('Invalid question page')
    cfg=service.settings();c=service.source_connection(cfg['source_db'])
    try:
        prefix,condition,args=where(filters)
        total=c.execute(prefix+'SELECT count(*) FROM resources r WHERE '+condition,args).fetchone()[0]
        nodes={r['id']:dict(r) for r in c.execute('SELECT id,parent_id,name,position FROM nodes')}
        cache_key=(str(cfg['source_db']),prefix+condition,json.dumps(args),Path(cfg['source_db']).stat().st_mtime_ns)
        ordered=_ORDER_CACHE.get(cache_key)
        if ordered is None:
            ordering=c.execute(prefix+'SELECT r.id,r.source,r.topic_id,r.title,r.position FROM resources r WHERE '+condition,args).fetchall()
            ordered=[r['id'] for r in sorted(ordering,key=lambda r:order_key(r,nodes))]
            if len(_ORDER_CACHE)>=6:_ORDER_CACHE.pop(next(iter(_ORDER_CACHE)))
            _ORDER_CACHE[cache_key]=ordered
        page=ordered[offset:offset+limit]
        fetched={r['id']:r for r in c.execute('SELECT r.id,r.source,r.grp,r.title,r.topic_id,r.qtype,r.type,r.difficulty,r.exam,r.year,r.status,r.fav,r.file_name,r.print_meta,r.answer,substr(r.question,1,350) question FROM resources r WHERE r.id IN ('+','.join('?' for _ in page)+')',page)} if page else {}
        rows=[fetched[i] for i in page if i in fetched]
        groups=list({r['grp'] for r in rows if r['grp']})
        solutions={}
        if groups:
            for r in c.execute("SELECT source,grp,count(*) n FROM resources WHERE part='sol' AND grp IN ("+','.join('?' for _ in groups)+') GROUP BY source,grp',groups):
                solutions[(r['source'],r['grp'])]=r['n']
        result=[]
        for row in rows:
            item=dict(row);issue=image_issue(item,cfg['asset_root'])
            item.update(selection_key=selection_key(item),path=node_path(nodes,item['topic_id']),
                        solution_parts=solutions.get((item['source'],item['grp']),0),ready=not issue,issue=issue)
            item.pop('print_meta');item.pop('file_name')
            result.append(item)
        return {'items':result,'total':total,'offset':offset,'limit':limit,'source_token':source_token()}
    finally:c.close()


def snapshot(resource_ids):
    """Freeze exact selected logical questions plus their own mapped solutions."""
    ids=list(dict.fromkeys(resource_ids))
    if not ids or len(ids)>MAX_SELECTION or any(not isinstance(v,int) or v<=0 for v in ids):
        raise ValueError(f'Select between one and {MAX_SELECTION} questions')
    cfg=service.settings();c=service.source_connection(cfg['source_db'])
    try:
        anchors={}
        for start in range(0,len(ids),400):
            page=ids[start:start+400]
            anchors.update({r['id']:dict(r) for r in c.execute('SELECT r.* FROM resources r WHERE '+ELIGIBLE+' AND r.id IN ('+','.join('?' for _ in page)+')',page)})
        if set(anchors)!=set(ids):raise ValueError('A selected question was removed or is not a question resource. Refresh the results.')
        selected_groups={(r['source'],r['grp']) for r in anchors.values() if r['grp']}
        grouped=defaultdict(list)
        names=list({g for _,g in selected_groups})
        for start in range(0,len(names),400):
            page=names[start:start+400]
            for row in c.execute('SELECT * FROM resources WHERE grp IN ('+','.join('?' for _ in page)+') ORDER BY id',page):
                row=dict(row)
                if (row['source'],row['grp']) in selected_groups:grouped[(row['source'],row['grp'])].append(row)
        nodes={r['id']:dict(r) for r in c.execute('SELECT * FROM nodes')}
        # Import in syllabus order (source, chapter, week, subtopic), never in checkbox-click order.
        ids=sorted(ids,key=lambda rid:order_key(anchors[rid],nodes))
        items=[];seen=set();all_ids=[]
        for rid in ids:
            anchor=anchors[rid];key=selection_key(anchor)
            if key in seen:continue
            seen.add(key)
            rows=grouped[(anchor['source'],anchor['grp'])] if anchor['grp'] else [anchor]
            qrows=[];srows=[]
            for row in rows:
                issue=image_issue(row,cfg['asset_root'])
                if issue:raise ValueError(f'{row["title"]}: {issue}')
                row=dict(row);row['source_part']=row['part'];row['part']=row['part'] or 'q'
                if row['part']=='q':qrows.append(row)
                elif row['part']=='sol':srows.append(row)
                else:raise ValueError(f'{anchor["title"]}: linked part role needs review in EJEE')
            # Preserve continuation order; ambiguous same-group questions must
            # not be silently merged into one extracted question.
            import re
            def order(row):
                m=re.search(r'\((\d+)\s*/\s*\d+\)',row['title'] or '')
                return (int(m[1]) if m else 1,row['position'],row['id'])
            qrows.sort(key=order);srows.sort(key=order)
            if len(qrows)>1 and not all(re.search(r'\(\d+\s*/\s*\d+\)',r['title'] or '') for r in qrows):
                raise ValueError(f'{anchor["title"]}: multiple question cards share a group; repair their mapping in EJEE first')
            ancestry={}
            for row in rows:
                lineage=[];node=row['topic_id'];visited=set()
                while node in nodes and node not in visited:
                    visited.add(node);lineage.append(nodes[node]);node=nodes[node]['parent_id']
                ancestry[str(row['id'])]=lineage
            linked=[r['id'] for r in rows];all_ids.extend(linked)
            marks=','.join('?' for _ in linked)
            items.append({'group':anchor['grp'] or f'resource-{rid}','number':str(len(items)+1),
                          'source_number':anchor['title'],'source_key':key,
                          'question_rows':qrows,'solution_rows':srows,'original_ancestry':ancestry,
                          'resource_crops':[dict(r) for r in c.execute(f'SELECT * FROM resource_crops WHERE resource_id IN ({marks})',linked)],
                          'resource_transcripts':[dict(r) for r in c.execute(f'SELECT * FROM resource_transcripts WHERE resource_id IN ({marks})',linked)],
                          'question_pages':[],'solution_pages':[]})
        # The content identity is independent of checkbox click order/title.
        identity=sorted([r for item in items for side in ('question_rows','solution_rows') for r in item[side]],key=lambda r:r['id'])
        fingerprint=hashlib.sha256(json.dumps(identity,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        return {'items':items,'selected_resource_ids':ids,'included_resource_ids':all_ids,'fingerprint':fingerprint}
    finally:c.close()


def details(resource_id,expected_source=None):
    if expected_source and expected_source!=source_token():raise ValueError('EJEE source changed. Refresh the results.')
    cfg=service.settings();c=service.source_connection(cfg['source_db'])
    try:
        row=c.execute('SELECT r.* FROM resources r WHERE '+ELIGIBLE+' AND r.id=?',(resource_id,)).fetchone()
        if row is None:raise FileNotFoundError('EJEE question not found')
        fields=('id','title','source','grp','type','qtype','difficulty','exam','year','shift','status','fav','altered','tags','question','answer','solution','uid','review','created_at')
        item={key:row[key] for key in fields}
        nodes={r['id']:dict(r) for r in c.execute('SELECT id,parent_id,name FROM nodes')}
        item['path']=node_path(nodes,row['topic_id'])
        item['selection_key']=selection_key(row)
        item['issue']=image_issue(row,cfg['asset_root']);item['ready']=not item['issue']
        parts=c.execute("SELECT id,title,part FROM resources WHERE source IS ? AND grp=? ORDER BY position,id",(row['source'],row['grp'])).fetchall() if row['grp'] else [row]
        item['question_parts']=[{'id':r['id'],'title':r['title']} for r in parts if (r['part'] or 'q')=='q']
        item['solution_parts']=sum(r['part']=='sol' for r in parts)
        return item
    finally:c.close()


def preview(resource_id,size='full',expected_source=None):
    from PIL import Image
    if size not in ('thumbnail','full'):raise ValueError('Invalid image size')
    if expected_source and expected_source!=source_token():raise ValueError('EJEE source changed. Refresh the results.')
    cfg=service.settings();c=service.source_connection(cfg['source_db'])
    try:
        row=c.execute('SELECT * FROM resources r WHERE '+ELIGIBLE+' AND r.id=?',(resource_id,)).fetchone()
        if row is None:raise FileNotFoundError('Question image not found')
        issue=image_issue(row,cfg['asset_root'])
        if issue:raise ValueError(issue)
        meta=json.loads(row['print_meta']);box=meta.get('box') or meta['qbox']
        with Image.open(Path(cfg['asset_root'])/row['file_name']) as im:
            im=im.convert('RGB');im=im.crop((int(box[0]*im.width),int(box[1]*im.height),int(box[2]*im.width+.999),int(box[3]*im.height+.999)))
            if size=='thumbnail':im.thumbnail((480,360))
            data=io.BytesIO();im.save(data,format='PNG')
        return data.getvalue()
    finally:c.close()
