#!/usr/bin/env node

/**
 * Validate mermaid transformations in all content files
 * This tests the actual transformation pipeline without browser dependencies
 */

const fs = require('fs');
const path = require('path');
const { MarkdownProcessor } = require('../out/markdownProcessor.js');

function extractMermaidCode(htmlOutput) {
    const match = htmlOutput.match(/data-mermaid-code="([^"]*)"/);
    if (!match) return null;
    
    return match[1]
        .replace(/&amp;/g, '&')
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&quot;/g, '"')
        .replace(/&#39;/g, "'");
}

function validateTransformations() {
    console.log('🔧 Validating mermaid transformations in content files...\n');
    
    const processor = new MarkdownProcessor();
    const contentDir = 'content';
    
    if (!fs.existsSync(contentDir)) {
        console.error('❌ Content directory not found:', contentDir);
        return;
    }
    
    const problematicPatterns = [
        {
            name: 'Object literal with string properties',
            pattern: /\{\s*\w+\s*:\s*string[^}]*\}/,
            examples: ['{ code : string; message : string }', '{ enabled : boolean }']
        },
        {
            name: 'Object literal arrays',
            pattern: /\{\s*\w+\s*:\s*\w+[^}]*\}\[\]/,
            examples: ['{ code : string }[]', '{ name : string }[]']
        },
        {
            name: 'Nested object structures',
            pattern: /\{\s*\w+\s*:\s*\{[^}]*\}[^}]*\}/,
            examples: ['{ prop : { nested : value } }']
        }
    ];
    
    function walkDirectory(dir) {
        const files = [];
        const items = fs.readdirSync(dir);
        
        for (const item of items) {
            const fullPath = path.join(dir, item);
            const stat = fs.statSync(fullPath);
            
            if (stat.isDirectory()) {
                files.push(...walkDirectory(fullPath));
            } else if (item.endsWith('.md')) {
                files.push(fullPath);
            }
        }
        
        return files;
    }
    
    const markdownFiles = walkDirectory(contentDir);
    console.log(`Found ${markdownFiles.length} markdown files to validate\n`);
    
    let totalDiagrams = 0;
    let validDiagrams = 0;
    let problematicDiagrams = 0;
    const problematicFiles = [];
    
    for (const filePath of markdownFiles) {
        try {
            const content = fs.readFileSync(filePath, 'utf8');
            
            // Check if file contains mermaid diagrams
            if (!content.includes('```mermaid')) {
                continue;
            }
            
            // Process the markdown
            const html = processor.convertToHtml(content);
            
            // Extract all mermaid diagrams
            const mermaidMatches = html.matchAll(/data-mermaid-code="([^"]*)"/g);
            const diagrams = Array.from(mermaidMatches);
            
            if (diagrams.length === 0) {
                continue;
            }
            
            const relativeFilePath = path.relative('.', filePath);
            console.log(`📄 ${relativeFilePath} (${diagrams.length} diagrams)`);
            
            let fileHasProblems = false;
            
            diagrams.forEach((match, index) => {
                totalDiagrams++;
                
                const decodedCode = extractMermaidCode(match[0]);
                if (!decodedCode) {
                    console.log(`  ❌ Diagram ${index + 1}: Failed to extract code`);
                    problematicDiagrams++;
                    fileHasProblems = true;
                    return;
                }
                
                // Check for problematic patterns
                let hasProblems = false;
                const foundProblems = [];
                
                problematicPatterns.forEach(({ name, pattern, examples }) => {
                    const matches = decodedCode.match(pattern);
                    if (matches) {
                        hasProblems = true;
                        foundProblems.push({ name, matches: matches.slice(0, 2) }); // Show first 2 matches
                    }
                });
                
                if (hasProblems) {
                    problematicDiagrams++;
                    fileHasProblems = true;
                    console.log(`  ❌ Diagram ${index + 1}: Contains problematic patterns`);
                    foundProblems.forEach(({ name, matches }) => {
                        console.log(`    • ${name}: ${matches.join(', ')}`);
                    });
                } else {
                    validDiagrams++;
                    console.log(`  ✅ Diagram ${index + 1}: OK`);
                }
            });
            
            if (fileHasProblems) {
                problematicFiles.push({
                    path: relativeFilePath,
                    diagramCount: diagrams.length
                });
            }
            
        } catch (error) {
            console.log(`  ❌ Error processing ${filePath}: ${error.message}`);
        }
    }
    
    // Summary
    console.log('\n================================================================================');
    console.log('📋 TRANSFORMATION VALIDATION SUMMARY');
    console.log('================================================================================\n');
    
    console.log(`📊 Statistics:`);
    console.log(`  Total diagrams: ${totalDiagrams}`);
    console.log(`  Valid diagrams: ${validDiagrams} (${((validDiagrams/totalDiagrams)*100).toFixed(1)}%)`);
    console.log(`  Problematic diagrams: ${problematicDiagrams} (${((problematicDiagrams/totalDiagrams)*100).toFixed(1)}%)`);
    console.log(`  Files with issues: ${problematicFiles.length}`);
    
    if (problematicFiles.length > 0) {
        console.log(`\n❌ FILES WITH PROBLEMATIC DIAGRAMS:`);
        problematicFiles.forEach(({ path, diagramCount }) => {
            console.log(`  • ${path} (${diagramCount} diagrams)`);
        });
        
        console.log(`\n🔧 RECOMMENDED ACTIONS:`);
        console.log(`1. Review the regex patterns in src/markdownProcessor.ts`);
        console.log(`2. The fixMermaidClassDiagramSyntax() method may need additional patterns`);
        console.log(`3. Test with: npm test -- transformation-validation.test.ts`);
    } else {
        console.log(`\n✅ All diagrams have valid syntax after transformation!`);
        console.log(`🎉 The mermaid rendering should work correctly in the browser.`);
    }
    
    return problematicDiagrams === 0;
}

// Run validation
const success = validateTransformations();
process.exit(success ? 0 : 1);