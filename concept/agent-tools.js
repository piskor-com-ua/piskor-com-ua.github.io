(() => {
  // document.modelContext is the current API; navigator covers earlier trials.
  const context = document.modelContext || navigator.modelContext;
  if (!context || typeof context.registerTool !== 'function' || document.__piskorModelContext === context) return;
  document.__piskorModelContext = context;

  let catalog;
  function readCatalog() {
    if (!catalog) {
      catalog = fetch('/project-catalog.json', { credentials: 'omit' })
        .then(response => {
          if (!response.ok) throw new Error('Project catalog is temporarily unavailable.');
          return response.json();
        })
        .then(data => {
          if (data.version !== 1 || !Array.isArray(data.projects)) throw new Error('Unsupported project catalog.');
          return data.projects;
        })
        .catch(error => { catalog = undefined; throw error; });
    }
    return catalog;
  }
  function validate(input, allowed) {
    if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('Provide an object with the documented fields.');
    if (Object.keys(input).some(key => !allowed.includes(key))) throw new Error('Unknown input field.');
    if (input.language !== undefined && !['uk', 'en'].includes(input.language)) throw new Error('Language must be uk or en.');
    return input.language || (document.documentElement.lang === 'en' ? 'en' : 'uk');
  }
  function text(value) {
    return value.toLocaleLowerCase().normalize('NFKC').replace(/[’‘]/g, "'");
  }
  const languageProperty = { type: 'string', enum: ['uk', 'en'], description: 'Page language; defaults to the current page.' };
  const tools = [
    {
      name: 'search_projects',
      description: 'Find published PISKOR architecture and interior projects by text and project year. Returns case links and the exact published labels and summaries.',
      inputSchema: {
        type: 'object',
        properties: {
          query: { type: 'string', maxLength: 200, description: 'Words from a project name, summary, location or case section.' },
          year: { type: 'integer', minimum: 1900, maximum: 2100 },
          language: languageProperty,
          limit: { type: 'integer', minimum: 1, maximum: 20, default: 10 }
        },
        additionalProperties: false
      },
      execute: async (input = {}) => {
        const lang = validate(input, ['query', 'year', 'language', 'limit']);
        if (input.query !== undefined && (typeof input.query !== 'string' || Array.from(input.query).length > 200)) throw new Error('Query must be a string of at most 200 characters.');
        if (input.year !== undefined && (!Number.isInteger(input.year) || input.year < 1900 || input.year > 2100)) throw new Error('Provide a project year between 1900 and 2100.');
        const limit = input.limit === undefined ? 10 : input.limit;
        if (!Number.isInteger(limit) || limit < 1 || limit > 20) throw new Error('Limit must be an integer between 1 and 20.');
        const terms = text(input.query || '').split(/\s+/).filter(Boolean);
        const projects = (await readCatalog()).filter(project => project.language === lang &&
          (input.year === undefined || input.year === project.year) &&
          terms.every(term => text([project.name, project.summary, project.label,
            ...project.facts.map(f => f.value), ...project.sections.map(s => s.text)].join(' ')).includes(term)));
        return JSON.stringify({ total: projects.length, projects: projects.slice(0, limit).map(({ id, name, url, year, summary, label }) => ({ id, name, url, year, summary, label })) });
      }
    },
    {
      name: 'get_project_details',
      description: 'Read a PISKOR case’s published facts and section links. Labels and text describe the source-confirmed scope; project proposals and installed systems retain their published wording.',
      inputSchema: {
        type: 'object', properties: {
          project_id: { type: 'string', maxLength: 100, pattern: '^[a-z0-9-]+$' },
          language: languageProperty
        }, required: ['project_id'], additionalProperties: false
      },
      execute: async input => {
        const lang = validate(input, ['project_id', 'language']);
        if (typeof input.project_id !== 'string' || input.project_id.length > 100 || !/^[a-z0-9-]+$/.test(input.project_id)) throw new Error('Provide a project_id returned by search_projects.');
        const project = (await readCatalog()).find(p => p.id === input.project_id && p.language === lang);
        if (!project) throw new Error('Project not found in the selected language.');
        return JSON.stringify(project);
      }
    },
    {
      name: 'get_contact_options',
      description: 'Read the studio’s public phone, WhatsApp and Viber links from this page.',
      inputSchema: { type: 'object', properties: {}, additionalProperties: false },
      execute: async (input = {}) => {
        validate(input, []);
        return JSON.stringify({ contacts: [...document.querySelectorAll('#contact a[href]')].map(link => ({
          name: link.textContent.replace(/↗/g, '').trim(),
          url: link.getAttribute('href')
        })) });
      }
    }
  ];
  for (const tool of tools) {
    tool.annotations = { readOnlyHint: true };
    try {
      Promise.resolve(context.registerTool(tool)).catch(() => {});
    } catch { /* Experimental API availability must not affect normal browsing. */ }
  }
})();
