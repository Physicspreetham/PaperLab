import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { compile } from 'svelte/compiler';
import { render } from 'svelte/server';
import { test } from 'node:test';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const temp = await fs.mkdtemp(path.join(root, '.model-picker-test-'));
try {
	const search = (await fs.readFile(path.join(root, 'src/lib/search.js'), 'utf8')).replace("import { browser } from '$app/environment';", 'const browser = false;');
	await fs.writeFile(path.join(temp, 'search.mjs'), search);
	for (const name of ['ModelPicker', 'ModelQuestion', 'QuestionBrowser', 'FilterDropdown', 'TopicTreePicker']) {
		let source = await fs.readFile(path.join(root, `src/lib/components/${name}.svelte`), 'utf8');
		for (const generate of ['client', 'server']) {
			const result = compile(source, { filename: `${name}.svelte`, generate });
			if (name.startsWith('Model')) assert.equal(result.warnings.length, 0);
		}
		source = source.replace("import { api } from '$lib/api.js';", 'const api = {};');
		source = source.replaceAll(/from '\$lib\/components\/([^']+)\.svelte'/g, "from './$1.mjs'");
		source = source.replace("from '$lib/search.js'", "from './search.mjs'");
		source = source.replaceAll(/from '\$lib\/([^']+)'/g, (_, file) => `from '${pathToFileURL(path.join(root, 'src/lib', file)).href}'`);
		await fs.writeFile(path.join(temp, `${name}.mjs`), compile(source, { generate: 'server' }).js.code);
	}
	// Full question segments load in the browser; SSR renders the loading state.
	await fs.writeFile(path.join(temp, 'AddToCart.mjs'), compile('<button>Cart</button>', { generate: 'server' }).js.code);
	await fs.writeFile(path.join(temp, 'Segments.mjs'), compile('<p>Segments</p>', { generate: 'server' }).js.code);
	const { default: Picker } = await import(pathToFileURL(path.join(temp, 'ModelPicker.mjs')).href);
	const props = {
		section: { id: 'S2', typeName: 'Single correct', units: 5 },
		fits: (type) => type === 'scq',
		taken: new Set(['1::11']), activeCartId: 'second',
		carts: [
			{ id: 'first', name: 'Other cart', items: [{ paperId: 2, number: '99', qtype: 'scq' }] },
			{ id: 'second', name: 'Chosen cart', items: [
				{ paperId: 1, number: '10', qtype: 'scq', exam: 'JEE Main', institute: 'Source institute', year: 2025 },
				{ paperId: 1, number: '11', qtype: 'scq' },
				{ paperId: 1, number: '12', qtype: 'msq' }
			] }
		], onAdd() {}, onClose() {}
	};
	await test('continuous reader shows every compatible full-question entry with navigation', () => {
		const { body } = render(Picker, { props });
		assert.match(body, /Select question 10/);
		assert.match(body, /Select question 11/);
		assert.match(body, /<nav[^>]*aria-label="Questions"/);
		assert.equal((body.match(/<article/g) ?? []).length, 2);
		assert.match(body, /<h2[^>]*>Question 10<\/h2>/);
		assert.match(body, /<h2[^>]*>Question 11<\/h2>/);
		assert.doesNotMatch(body, /Reader view|data-view=/);
		assert.doesNotMatch(body, /Select question 12|Select question 99/);
		assert.equal((body.match(/role="tab"/g) ?? []).length, 2);
		assert.match(body, /Source institute/);
		assert.match(body, /JEE Main/);
		assert.match(body, /Already in the paper/);
		assert.match(body, /Add to section/);
		assert.doesNotMatch(body, /class="thumb"/);
	});
	await test('cart with no compatible types explains how to continue', () => {
		const { body } = render(Picker, { props: { ...props, fits: () => false } });
		assert.match(body, /No questions in this cart fit this section/);
		assert.doesNotMatch(body, /Select question 10/);
	});
	await fs.writeFile(path.join(temp, 'BrowserFixture.mjs'), compile(`<script>import Browser from './QuestionBrowser.mjs'; let { items, mode } = $props();</script><Browser {items} {mode}>{#snippet tools()}<h1>Question tools</h1>{/snippet}</Browser>`, { generate: 'server' }).js.code);
	const { default: BrowserFixture } = await import(pathToFileURL(path.join(temp, 'BrowserFixture.mjs')).href);
	for (const mode of ['search', 'cart']) {
		await test(`${mode} browser renders thumbnail navigation and continuous full questions with correct actions`, () => {
			const { body } = render(BrowserFixture, { props: { items: props.carts[1].items, mode } });
			assert.match(body, /aria-label="Question thumbnails"/);
			assert.equal((body.match(/<article/g) ?? []).length, 3);
			assert.match(body, /Question 10/);
			assert.match(body, /Question 12/);
			assert.doesNotMatch(body, /Add to section|Select question/);
			assert.match(body, mode === 'cart' ? /Remove from cart/ : /<button>Cart<\/button>/);
		});
	}

} finally {
	assert.equal(path.dirname(path.resolve(temp)), root);
	await fs.rm(temp, { recursive: true, force: true });
}
