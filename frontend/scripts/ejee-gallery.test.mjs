import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createWheelPager } from '../src/lib/ejeeGallery.js';

test('wheel advances only after a deliberate gesture, with momentum cooldown',()=>{
 const slide=createWheelPager();
 assert.equal(slide({deltaY:20},0),0);
 assert.equal(slide({deltaY:30},50),1);
 assert.equal(slide({deltaY:120},80),0);
 assert.equal(slide({deltaY:-120},600),-1);
});
test('line wheels, horizontal trackpads, stale partial gestures and zoom modifiers',()=>{
 const slide=createWheelPager();
 assert.equal(slide({deltaY:3,deltaMode:1},0),1);
 assert.equal(slide({deltaY:1,deltaX:-60},500),-1);
 assert.equal(slide({deltaY:200,ctrlKey:true},1000),0);
 assert.equal(slide({deltaY:200,metaKey:true},1000),0);
 assert.equal(slide({deltaY:20},1000),0);
 assert.equal(slide({deltaY:30},1500),0);
 assert.equal(slide({deltaY:20},1510),1);
});
