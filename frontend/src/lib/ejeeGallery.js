/** Never enlarge small sources; limit high-resolution scans to reading width. */
export function initialImageZoom(naturalWidth, viewportWidth) {
	if (!(naturalWidth > 0)) return 100;
	return Math.max(1, Math.floor(Math.min(1, 900/naturalWidth, Math.max(1,viewportWidth-32)/naturalWidth)*100));
}

/** Normalize mouse/trackpad wheel bursts into deliberate single-question slides. */
export function createWheelPager({ threshold = 45, cooldown = 450 } = {}) {
	let sum=0,lastSlide=-Infinity,lastEvent=-Infinity;
	return (event,now) => {
		if (event.ctrlKey || event.metaKey || now-lastSlide<cooldown) return 0;
		const delta=(Math.abs(event.deltaX || 0)>Math.abs(event.deltaY || 0) ? event.deltaX : event.deltaY) * (event.deltaMode===1 ? 16 : event.deltaMode===2 ? 600 : 1);
		if (!delta) return 0;
		if (now-lastEvent>250 || Math.sign(sum)!==Math.sign(delta)) sum=0;
		lastEvent=now;sum+=delta;
		if (Math.abs(sum)<threshold) return 0;
		const direction=Math.sign(sum);sum=0;lastSlide=now;
		return direction;
	};
}

/** Only exit a fullscreen session started by this viewer, never the user's own. */
export function createViewerFullscreen(doc) {
	let owned=false,pending=Promise.resolve();
	return {
		owns:()=>owned,
		enter() {
			if(doc.fullscreenElement || !doc.documentElement.requestFullscreen) return pending;
			owned=true;
			try {pending=Promise.resolve(doc.documentElement.requestFullscreen()).catch(()=>{owned=false;});}
			catch {owned=false;pending=Promise.resolve();}
			return pending;
		},
		async leave() {
			await pending;
			if(owned && doc.fullscreenElement===doc.documentElement) {
				try {await doc.exitFullscreen();} catch { /* already exited by Esc */ }
			}
			owned=false;
		}
	};
}

/** Same order as the backend: module/chapter/week/topic positions, then source, then natural title. */
export function sortByImportOrder(rows,nodes) {
	const byId=new Map(nodes.map(n=>[n.id,n])),memo=new Map();
	const natural=t=>String(t||'').split(/(\d+)/).map(p=>/^\d+$/.test(p)?[0,Number(p)]:[1,p.toLowerCase()]);
	const syllabus=topic=>{
		if(memo.has(topic))return memo.get(topic);
		const path=[],seen=new Set();let node=byId.get(topic);
		while(node && !seen.has(node.id)){seen.add(node.id);path.unshift([node.position ?? 2**30,node.id]);node=byId.get(node.parent_id);}
		memo.set(topic,path);return path;
	};
	const cmp=(a,b)=>{
		const n=Math.min(a.length,b.length);
		for(let i=0;i<n;i++){
			const x=a[i],y=b[i];
			if(Array.isArray(x)&&Array.isArray(y)){const r=cmp(x,y);if(r)return r;continue;}
			if(x<y)return -1;if(x>y)return 1;
		}
		return a.length-b.length;
	};
	const key=r=>[(()=>{const s=syllabus(r.topic_id);return s.length?[0,s]:[1,[]];})(),r.source?[0,String(r.source).toLowerCase()]:[1,''],natural(r.title),[r.id]];
	return [...rows].sort((a,b)=>cmp(key(a),key(b)));
}
