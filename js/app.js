// Coach Database App

const API_BASE = 'https://coach-database-api.fly.dev';

// Set current date in header
(function() {
  const el = document.getElementById('current-date');
  if (el) {
    const now = new Date();
    el.textContent = now.toLocaleDateString('en-US', { 
      weekday: 'short', year: 'numeric', month: 'short', day: '2-digit' 
    });
  }
})();

class CoachDatabase {
  constructor() {
    this.coaches = [];
    this.filteredCoaches = [];
    this.metadata = {};
    this.currentSort = { field: 'total_pay', direction: 'desc' };
    this.headOnly = false; // Default to showing all coaches
    this.availableYears = [];
    this.selectedYear = null;
    this.previousYear = null;
    this.changes = null;
    this.newHireKeys = new Set();
    this.init();
  }

  async init() {
    try {
      await this.loadYears();
      await this.loadData();
      await this.loadChanges();
      this.populateConferences();
      this.setupEventListeners();
      this.renderChangesPanel();
      this.render();
    } catch (error) {
      console.error('Error initializing:', error);
      document.getElementById('coaches-tbody').innerHTML = 
        '<tr><td colspan="7" class="loading">Error loading data. Please refresh.</td></tr>';
    }
  }

  async loadYears() {
    const yearSelect = document.getElementById('year-filter');
    if (!yearSelect) return;

    try {
      const resp = await fetch(`${API_BASE}/years`);
      if (!resp.ok) return;
      const data = await resp.json();
      const years = Array.isArray(data.years) ? data.years : [];
      this.availableYears = years;
      this.selectedYear = (data.latest || years[0]) || null;
      this.previousYear = this.getPreviousYear(this.selectedYear);

      yearSelect.innerHTML = '';
      years.forEach(y => {
        const option = document.createElement('option');
        option.value = String(y);
        option.textContent = String(y);
        yearSelect.appendChild(option);
      });
      if (this.selectedYear) yearSelect.value = String(this.selectedYear);
    } catch (e) {
      // Fallback: allow API default year behavior.
    }
  }

  getPreviousYear(year) {
    if (!year) return null;
    const prior = (this.availableYears || []).filter(y => y < year).sort((a, b) => b - a);
    return prior.length ? prior[0] : (year - 1);
  }

  async loadData() {
    const yearParam = this.selectedYear ? String(this.selectedYear) : null;

    // Fetch stats for metadata
    const statsUrl = new URL(`${API_BASE}/stats`);
    if (yearParam) statsUrl.searchParams.set('year', yearParam);
    const statsResp = await fetch(statsUrl.toString());
    const stats = await statsResp.json();
    
    // Fetch coaches from API (get all coaches)
    const params = new URLSearchParams({ limit: '2500' });
    if (this.headOnly) params.set('head_only', 'true');
    if (yearParam) params.set('year', yearParam);
    
    const coachResp = await fetch(`${API_BASE}/coaches?${params}`);
    const coaches = await coachResp.json();
    
    // Map API fields to expected format
    this.coaches = coaches.map((c, idx) => ({
      rank: idx + 1,
      id: c.id,
      coach: c.name,
      school: c.school || 'Unknown',
      conference: c.conference || 'Unknown',
      position: c.position,
      isHeadCoach: c.is_head_coach,
      totalPay: c.total_pay,
      maxBonus: null, // Not in list endpoint
      buyout: null,   // Not in list endpoint
      schoolSlug: c.school_slug
    }));
    
    this.filteredCoaches = [...this.coaches];
    this.metadata = {
      year: stats.year || this.selectedYear,
      totalCoaches: stats.head_coaches + stats.assistants,
      headCoaches: stats.head_coaches,
      assistants: stats.assistants,
      schools: stats.schools
    };
    
    // Update last updated
    document.getElementById('last-updated').textContent = 
      `${this.metadata.year || ''} season | ${this.metadata.headCoaches} head coaches | ${this.metadata.assistants} assistants | ${this.metadata.schools} schools`;
  }

  async loadChanges() {
    this.changes = null;
    this.newHireKeys = new Set();

    if (!this.selectedYear) return;
    const prev = this.getPreviousYear(this.selectedYear);
    this.previousYear = prev;
    if (!prev) return;

    try {
      const resp = await fetch(`${API_BASE}/changes?from=${encodeURIComponent(prev)}&to=${encodeURIComponent(this.selectedYear)}`);
      if (!resp.ok) return;
      const data = await resp.json();
      this.changes = data;

      const hires = Array.isArray(data.new_hires) ? data.new_hires : [];
      hires.forEach(h => {
        if (!h || !h.school_slug || !h.name) return;
        this.newHireKeys.add(`${h.school_slug}|${h.name}`);
      });
    } catch (e) {
      // Ignore; changes are optional for the UI.
    }
  }

  populateConferences() {
    const conferences = [...new Set(this.coaches.map(c => c.conference))].sort();
    const select = document.getElementById('conference-filter');

    // Reset (keep first option)
    while (select.options.length > 1) select.remove(1);
    
    conferences.forEach(conf => {
      const option = document.createElement('option');
      option.value = conf;
      option.textContent = conf;
      select.appendChild(option);
    });
  }

  setupEventListeners() {
    // Year filter
    const yearFilter = document.getElementById('year-filter');
    if (yearFilter) {
      yearFilter.addEventListener('change', async (e) => {
        const value = e.target.value;
        this.selectedYear = value ? parseInt(value, 10) : null;
        this.previousYear = this.getPreviousYear(this.selectedYear);
        await this.loadData();
        await this.loadChanges();
        this.populateConferences();
        this.renderChangesPanel();
        this.applyFilters();
      });
    }

    // Search
    const searchInput = document.getElementById('search');
    let debounceTimer;
    searchInput.addEventListener('input', (e) => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => this.applyFilters(), 200);
    });

    // Conference filter
    document.getElementById('conference-filter').addEventListener('change', () => this.applyFilters());

    // Head coaches only toggle (if exists)
    const headOnlyToggle = document.getElementById('head-only-toggle');
    if (headOnlyToggle) {
      headOnlyToggle.checked = this.headOnly;
      headOnlyToggle.addEventListener('change', async (e) => {
        this.headOnly = e.target.checked;
        await this.loadData();
        await this.loadChanges();
        this.renderChangesPanel();
        this.applyFilters();
      });
    }

    // Changes panel toggle
    const changesToggle = document.getElementById('changes-toggle');
    const changesPanel = document.getElementById('changes-panel');
    if (changesToggle && changesPanel) {
      changesToggle.addEventListener('click', () => {
        const isHidden = changesPanel.hasAttribute('hidden');
        if (isHidden) changesPanel.removeAttribute('hidden');
        else changesPanel.setAttribute('hidden', '');
        changesToggle.setAttribute('aria-expanded', isHidden ? 'true' : 'false');
      });
    }

    // Sort dropdown
    document.getElementById('sort-by').addEventListener('change', (e) => {
      const [field, direction] = e.target.value.split('-');
      this.currentSort = { field, direction: direction || 'asc' };
      this.applyFilters();
    });

    // Table header sorting
    document.querySelectorAll('th[data-sort]').forEach(th => {
      th.addEventListener('click', () => {
        const field = th.dataset.sort;
        if (this.currentSort.field === field) {
          this.currentSort.direction = this.currentSort.direction === 'asc' ? 'desc' : 'asc';
        } else {
          this.currentSort = { field, direction: 'asc' };
        }
        this.updateSortIndicators();
        this.applyFilters();
      });
    });
  }

  updateSortIndicators() {
    document.querySelectorAll('th[data-sort]').forEach(th => {
      th.classList.remove('sort-asc', 'sort-desc');
      if (th.dataset.sort === this.currentSort.field) {
        th.classList.add(`sort-${this.currentSort.direction}`);
      }
    });
  }

  applyFilters() {
    const searchTerm = document.getElementById('search').value.toLowerCase();
    const conference = document.getElementById('conference-filter').value;

    this.filteredCoaches = this.coaches.filter(coach => {
      // Search filter - matches name, school, or position
      if (searchTerm) {
        const matchesSearch = 
          coach.coach.toLowerCase().includes(searchTerm) ||
          coach.school.toLowerCase().includes(searchTerm) ||
          (coach.position && coach.position.toLowerCase().includes(searchTerm));
        if (!matchesSearch) return false;
      }

      // Conference filter
      if (conference && coach.conference !== conference) {
        return false;
      }

      return true;
    });

    // Sort
    this.filteredCoaches.sort((a, b) => {
      const field = this.currentSort.field;
      const dir = this.currentSort.direction === 'asc' ? 1 : -1;

      let aVal = a[field];
      let bVal = b[field];

      // Handle nulls
      if (aVal === null) aVal = this.currentSort.direction === 'asc' ? Infinity : -Infinity;
      if (bVal === null) bVal = this.currentSort.direction === 'asc' ? Infinity : -Infinity;

      if (typeof aVal === 'string') {
        return aVal.localeCompare(bVal) * dir;
      }
      return (aVal - bVal) * dir;
    });

    this.render();
  }

  renderChangesPanel() {
    const panel = document.getElementById('changes-panel');
    if (!panel) return;

    if (!this.selectedYear || !this.previousYear) {
      panel.innerHTML = `<div class="changes-muted">Year-over-year changes unavailable.</div>`;
      return;
    }

    if (!this.changes) {
      panel.innerHTML = `
        <div class="changes-header">
          <div class="changes-title">Year Changes</div>
          <div class="changes-subtitle">${this.previousYear} → ${this.selectedYear}</div>
        </div>
        <div class="changes-muted">Changes not loaded yet.</div>
      `;
      return;
    }

    const hires = Array.isArray(this.changes.new_hires) ? this.changes.new_hires : [];
    const deps = Array.isArray(this.changes.departures) ? this.changes.departures : [];
    const promos = Array.isArray(this.changes.promotions) ? this.changes.promotions : [];

    const top = (arr, n) => arr.slice(0, n);
    const li = (text) => `<li>${text}</li>`;

    panel.innerHTML = `
      <div class="changes-header">
        <div class="changes-title">Year Changes</div>
        <div class="changes-subtitle">${this.previousYear} → ${this.selectedYear} · ${hires.length} hires · ${deps.length} departures · ${promos.length} role changes</div>
      </div>
      <div class="changes-grid">
        <div class="changes-card">
          <h4>New Hires</h4>
          <ul class="changes-list">
            ${hires.length ? top(hires, 12).map(h => li(`${this.escapeHtml(h.name)} — ${this.escapeHtml(h.school)}`)).join('') : `<li class="changes-muted">None detected.</li>`}
          </ul>
        </div>
        <div class="changes-card">
          <h4>Departures</h4>
          <ul class="changes-list">
            ${deps.length ? top(deps, 12).map(d => li(`${this.escapeHtml(d.name)} — ${this.escapeHtml(d.school)}`)).join('') : `<li class="changes-muted">None detected.</li>`}
          </ul>
        </div>
        <div class="changes-card">
          <h4>Role Changes</h4>
          <ul class="changes-list">
            ${promos.length ? top(promos, 12).map(p => li(`${this.escapeHtml(p.name)} — ${this.escapeHtml(p.school)} (${this.escapeHtml(p.from_position || '—')} → ${this.escapeHtml(p.to_position || '—')})`)).join('') : `<li class="changes-muted">None detected.</li>`}
          </ul>
        </div>
      </div>
    `;
  }

  formatMoney(amount, compact = false) {
    if (!amount) return '—';
    
    if (compact || amount >= 1e9) {
      if (amount >= 1e9) return `$${(amount / 1e9).toFixed(1)}B`;
      if (amount >= 1e6) return `$${(amount / 1e6).toFixed(1)}M`;
      return `$${(amount / 1e3).toFixed(0)}K`;
    }
    
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0
    }).format(amount);
  }

  getConfClass(conference) {
    const confMap = {
      'SEC': 'conf-SEC',
      'Big 10': 'conf-Big10',
      'Big 12': 'conf-Big12',
      'ACC': 'conf-ACC',
      'MWC': 'conf-MWC'
    };
    return confMap[conference] || 'conf-Other';
  }

  render() {
    const tbody = document.getElementById('coaches-tbody');

    if (this.filteredCoaches.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" class="loading">No coaches match your filters.</td></tr>';
      return;
    }

    // Render rows with clickable coach names
    tbody.innerHTML = this.filteredCoaches.map((coach, idx) => `
      <tr>
        <td>${coach.rank}</td>
        <td>
          <div class="coach-name clickable" data-idx="${idx}" tabindex="0">
            ${this.escapeHtml(coach.coach)}
            ${this.newHireKeys.has(`${coach.schoolSlug}|${coach.coach}`) ? '<span class="new-badge">New</span>' : ''}
          </div>
        </td>
        <td>
          <span class="position-badge ${coach.isHeadCoach ? 'head-coach' : ''}">${this.escapeHtml(coach.position || '—')}</span>
        </td>
        <td>
          <div class="school-name">${this.escapeHtml(coach.school)}</div>
        </td>
        <td>
          <span class="conf-badge ${this.getConfClass(coach.conference)}">${coach.conference}</span>
        </td>
        <td class="number">
          ${coach.totalPay 
            ? `<span class="money">${this.formatMoney(coach.totalPay)}</span>` 
            : '<span class="undisclosed">—</span>'}
        </td>
      </tr>
    `).join('');

    // Add click event listeners for coach details
    tbody.querySelectorAll('.coach-name.clickable').forEach(el => {
      el.addEventListener('click', async (e) => {
        const idx = parseInt(el.getAttribute('data-idx'));
        const coach = this.filteredCoaches[idx];
        await this.showCoachModal(coach);
      });
      el.addEventListener('keydown', async (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          const idx = parseInt(el.getAttribute('data-idx'));
          const coach = this.filteredCoaches[idx];
          await this.showCoachModal(coach);
        }
      });
    });
  }

  // Fetch Wikipedia data (summary/details) for a coach
  async fetchWikipediaData(coachName) {
    // Wikipedia REST API summary endpoint
    const base = 'https://en.wikipedia.org/api/rest_v1/page/summary/'
    const tryTitles = [
      coachName.replace(/ /g, '_'),
      coachName.replace(/ /g, '_') + '_(American_football_coach)',
      coachName.replace(/ /g, '_') + '_(American_football)'
    ];
    for (let title of tryTitles) {
      try {
        const resp = await fetch(`${base}${encodeURIComponent(title)}`);
        if (resp.ok) {
          const data = await resp.json();
          if (!data.title || data.type === 'disambiguation') continue;
          return data;
        }
      } catch (e) {}
    }
    return null;
  }

  async fetchCareerHistory(coachId) {
    if (!coachId) return [];
    try {
      const resp = await fetch(`${API_BASE}/coaches/${coachId}/career`);
      if (!resp.ok) return [];
      const data = await resp.json();
      return Array.isArray(data) ? data : [];
    } catch (e) {
      return [];
    }
  }

  formatYearRange(startYear, endYear) {
    if (!startYear && !endYear) return '—';
    if (!endYear || startYear === endYear) return `${startYear}`;
    return `${startYear}\u2013${endYear}`; // en dash
  }

  renderCareerHistory(stints) {
    if (!stints || stints.length === 0) {
      return `
        <div class="modal-section">
          <h4>Career History</h4>
          <div class="modal-empty"><em>Career history not available.</em></div>
        </div>
      `;
    }

    const items = stints.map(s => {
      const years = this.formatYearRange(s.start_year, s.end_year);
      const position = this.escapeHtml(s.position || '—');
      const school = this.escapeHtml(s.school || 'Unknown');
      return `
        <li class="career-item">
          <div class="career-dot" aria-hidden="true"></div>
          <div class="career-content">
            <div class="career-main">
              <span class="career-position">${position}</span>
              <span class="career-school">${school}</span>
            </div>
            <div class="career-years">${this.escapeHtml(years)}</div>
          </div>
        </li>
      `;
    }).join('');

    return `
      <div class="modal-section">
        <h4>Career History</h4>
        <ul class="career-history">
          ${items}
        </ul>
      </div>
    `;
  }

  // Show modal with coach details (Wikipedia + fallback)
  async showCoachModal(coach) {
    const modal = document.getElementById('coach-modal');
    const close = document.getElementById('modal-close');
    const body = document.getElementById('modal-body');

    // Show loading first
    body.innerHTML = `<div class="modal-loading">Loading coach details...</div>`;
    modal.style.display = 'block';

    // Accessibility: close on Esc
    document.addEventListener('keydown', this._modalKeyListener = function(evt) {
      if (evt.key === 'Escape') {
        modal.style.display = 'none';
      }
    });

    // Close modal logic
    close.onclick = () => { modal.style.display = 'none'; };
    window.onclick = (event) => {
      if (event.target == modal) modal.style.display = 'none';
    };

    // Fetch Wikipedia info
    let wiki = await this.fetchWikipediaData(coach.coach);
    let photo = wiki && wiki.thumbnail ? wiki.thumbnail.source : null;
    let bio = wiki && wiki.extract ? wiki.extract : null;
    let pageUrl = wiki && wiki.content_urls && wiki.content_urls.desktop ? wiki.content_urls.desktop.page : null;
    let desc = wiki && wiki.description ? wiki.description : null;

    // Fetch career history (uses historical staff data in DB, when available)
    const careerStints = await this.fetchCareerHistory(coach.id);

    // Try crude coaching tree extraction. Lineage: under (head coach ...)
    let lineage = null;
    if (bio) {
      const match = bio.match(/under (?:head coach )?([A-Z][a-z]+ [A-Z][a-z]+)/);
      lineage = match ? match[1] : null;
    }

    // Modal content
    body.innerHTML = `
      <div class="modal-header">
        ${photo ? `<img src="${photo}" alt="${coach.coach}" class="modal-photo">` : ''}
        <div class="modal-title-section">
          <h2>${this.escapeHtml(coach.coach)}</h2>
          <h3>${this.escapeHtml(coach.school)}${desc ? ` &mdash; <span class='modal-desc'>${desc}</span>` : ''}</h3>
          ${pageUrl ? `<a href="${pageUrl}" target="_blank" class="modal-wiki-link">Wikipedia</a>` : ''}
        </div>
      </div>
      <div class="modal-bio">${bio ? this.escapeHtml(bio) : '<em>No detailed biography found.</em>'}</div>
      ${this.renderCareerHistory(careerStints)}
      <div class="modal-lineage">${lineage ? `<strong>Coaching Tree:</strong> ${this.escapeHtml(lineage)}` : ''}</div>
    `;
  }

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
  }
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
  new CoachDatabase();
});
