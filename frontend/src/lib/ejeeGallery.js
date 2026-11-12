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
