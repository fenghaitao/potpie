import * as fs from 'fs';
import * as path from 'path';

export interface DeepWikiPage {
	id: string;
	title: string;
	description?: string;
	importance?: string;
	relevantFiles?: string[];
	parentSection?: string;
	fileName: string; // Computed from title (e.g., "Getting_Started.md")
}

export interface DeepWikiSection {
	id: string;
	title: string;
	pages: DeepWikiPage[];
	subsections: DeepWikiSection[];
}

export interface DeepWikiStructure {
	title: string;
	description: string;
	sections: DeepWikiSection[];
	pagesMap: Map<string, DeepWikiPage>; // page-id -> page
}

/**
 * Parse wiki_structure.xml to extract the hierarchical structure
 */
export class DeepWikiXmlParser {
	/**
	 * Convert page title to filename (e.g., "Getting Started" -> "Getting_Started.md")
	 */
	private static titleToFileName(title: string): string {
		return title.replace(/\s+/g, '_') + '.md';
	}

	/**
	 * Parse the wiki_structure.xml file
	 */
	static parse(xmlFilePath: string): DeepWikiStructure {
		const xmlContent = fs.readFileSync(xmlFilePath, 'utf-8');
		
		// Simple XML parsing (we could use a proper XML parser library, but for this structure, regex works)
		const structure: DeepWikiStructure = {
			title: this.extractValue(xmlContent, 'title') || 'DeepWiki Documentation',
			description: this.extractValue(xmlContent, 'description') || '',
			sections: [],
		pagesMap: new Map()
	};

	// First, parse all pages to build the map
	// Extract root-level pages section (after </sections> to avoid matching <pages> inside sections)
	const rootPagesMatch = xmlContent.match(/<\/sections>\s*<pages>([\s\S]*?)<\/pages>/);
	
	if (rootPagesMatch) {
		const pagesSection = rootPagesMatch[1];
		
		// Use a more robust regex that handles the page structure
		const pageRegex = /<page\s+id="([^"]+)">([\s\S]*?)<\/page>/g;
		let match;
		while ((match = pageRegex.exec(pagesSection)) !== null) {
			const pageId = match[1];
			const pageContent = match[2];
			
			const page: DeepWikiPage = {
				id: pageId,
				title: this.extractValue(pageContent, 'title') || '',
				description: this.extractValue(pageContent, 'description'),
				importance: this.extractValue(pageContent, 'importance'),
				parentSection: this.extractValue(pageContent, 'parent_section'),
				relevantFiles: this.extractMultipleValues(pageContent, 'file_path'),
				fileName: ''
			};
			
			page.fileName = this.titleToFileName(page.title);
			structure.pagesMap.set(pageId, page);
		}
	}		// Then, parse sections hierarchy
		const sectionsContent = this.extractSection(xmlContent, 'sections');
		if (sectionsContent) {
			structure.sections = this.parseSections(sectionsContent, structure.pagesMap);
		}

		return structure;
	}

	/**
	 * Parse sections recursively
	 */
	private static parseSections(sectionsXml: string, pagesMap: Map<string, DeepWikiPage>): DeepWikiSection[] {
		const sections: DeepWikiSection[] = [];
		const sectionRegex = /<section\s+id="([^"]+)">([\s\S]*?)<\/section>/g;
		let match;

		while ((match = sectionRegex.exec(sectionsXml)) !== null) {
			const sectionId = match[1];
			const sectionContent = match[2];
			
			const section: DeepWikiSection = {
				id: sectionId,
				title: this.extractValue(sectionContent, 'title') || '',
				pages: [],
				subsections: []
			};

			// Extract page references
			const pagesSection = this.extractSection(sectionContent, 'pages');
			if (pagesSection) {
				const pageRefRegex = /<page_ref>([^<]+)<\/page_ref>/g;
				let pageRefMatch;
				while ((pageRefMatch = pageRefRegex.exec(pagesSection)) !== null) {
					const pageId = pageRefMatch[1];
					const page = pagesMap.get(pageId);
					if (page) {
						section.pages.push(page);
					}
				}
			}

			// Extract subsections recursively
			const subsectionsSection = this.extractSection(sectionContent, 'subsections');
			if (subsectionsSection) {
				section.subsections = this.parseSections(subsectionsSection, pagesMap);
			}

			sections.push(section);
		}

		return sections;
	}

	/**
	 * Extract a section from XML (e.g., <pages>...</pages>)
	 */
	private static extractSection(xml: string, tagName: string): string | null {
		const regex = new RegExp(`<${tagName}[^>]*>([\\s\\S]*?)<\\/${tagName}>`, 'i');
		const match = xml.match(regex);
		return match ? match[1] : null;
	}

	/**
	 * Extract a single value from XML (e.g., <title>value</title>)
	 */
	private static extractValue(xml: string, tagName: string): string | undefined {
		const regex = new RegExp(`<${tagName}[^>]*>([^<]*)<\\/${tagName}>`, 'i');
		const match = xml.match(regex);
		return match ? match[1].trim() : undefined;
	}

	/**
	 * Extract multiple values from XML (e.g., multiple <file_path>...)
	 */
	private static extractMultipleValues(xml: string, tagName: string): string[] {
		const regex = new RegExp(`<${tagName}[^>]*>([^<]*)<\\/${tagName}>`, 'gi');
		const values: string[] = [];
		let match;
		while ((match = regex.exec(xml)) !== null) {
			values.push(match[1].trim());
		}
		return values;
	}
}
