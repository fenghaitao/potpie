const esbuild = require('esbuild');

const production = process.argv.includes('--production');
const watch = process.argv.includes('--watch');

/**
 * @type {import('esbuild').Plugin}
 */
const esbuildProblemMatcherPlugin = {
	name: 'esbuild-problem-matcher',

	setup(build) {
		build.onStart(() => {
			console.log('[watch] build started');
		});
		build.onEnd(result => {
			result.errors.forEach(({ text, location }) => {
				console.error(`✘ [ERROR] ${text}`);
				console.error(`    ${location.file}:${location.line}:${location.column}:`);
			});
			console.log('[watch] build finished');
		});
	}
};

async function main() {
	const ctx = await esbuild.context({
		entryPoints: ['src/extension.ts'],
		bundle: true,
		format: 'cjs',
		minify: production,
		sourcemap: !production,
		sourcesContent: false,
		platform: 'node',
		outfile: 'dist/extension.js',
		external: ['vscode'],
		logLevel: 'silent',
		plugins: [esbuildProblemMatcherPlugin],
		metafile: true
	});

	if (watch) {
		await ctx.watch();
	} else {
		await ctx.rebuild();
		const result = await ctx.rebuild();
		
		// Print bundle analysis
		console.log('\n📦 Bundle Analysis:');
		const outputs = result.metafile.outputs['dist/extension.js'];
		console.log(`  Size: ${(outputs.bytes / 1024).toFixed(2)} KB`);
		console.log(`  Inputs: ${Object.keys(result.metafile.inputs).length} files`);
		
		await ctx.dispose();
	}
}

main().catch(e => {
	console.error(e);
	process.exit(1);
});
