import assert from 'node:assert/strict';
import { packSlides, slideTitle, SLIDE_BUDGET } from '../src/lib/pptxSlides.js';

const u = (html, weight, opt = false) => ({ html, weight, opt });
// short question: one slide
assert.equal(packSlides([u('<p>q</p>', 100), u('<p>A) x</p>', 10, true), u('<p>B) y</p>', 10, true)]).length, 1);
// long question splits, order preserved, options stay together
const long = [u('<p>1</p>', 400), u('<p>2</p>', 400), u('<p>A)</p>', 50, true), u('<p>B)</p>', 50, true)];
const s = packSlides(long);
assert.equal(s.length, 2);
assert.ok(s[1].includes('<p>2</p>') && s[1].includes('<p>A)</p>') && s[1].includes('<p>B)</p>'));
// an oversized unit is never cut, gets its own slide
assert.equal(packSlides([u('<p>a</p>', 50), u('<img>', SLIDE_BUDGET + 500), u('<p>b</p>', 50)]).length, 3);
assert.equal(packSlides([]).length, 1);
assert.equal(slideTitle('4', 0), 'Question 4');
assert.equal(slideTitle('4', 2), 'Question 4 (cont.)');
console.log('pptx-slides ok');
