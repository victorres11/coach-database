// Coach Database App

class CoachDatabase {
  constructor() {
    this.coaches = [];
    this.filteredCoaches = [];
    this.metadata = {};
    this.currentSort = { field: 'rank', direction: 'asc' };
    this.init();
  }

  async init() {
    try {
      await this.loadData();
      this.populateConferences();
      this.setupEventListeners();
      this.updateStats();
      this.render();
    } catch (error) {
      console.error('Error initializing:', error);
      document.getElementById('coaches-tbody').innerHTML = 
        '<tr><td colspan="7" class="loading">Error loading data. Please refresh.</td></tr>';
    }
  }

  async loadData() {
    const response = await fetch('data/coaches.json');
    const data = await response.json();
    this.metadata = data.metadata;
    this.coaches = data.coaches;
    this.filteredCoaches = [...this.coaches];
    
    // Update last updated
    document.getElementById('last-updated').textContent = 
      `Last updated: ${new Date(this.metadata.lastUpdated).toLocaleDateString()}`;
  }

  populateConferences() {
    const conferences = [...new Set(this.coaches.map(c => c.conference))].sort();
    const select = document.getElementById('conference-filter');
    
    conferences.forEach(conf => {
      const option = document.createElement('option');
      option.value = conf;
      option.textContent = conf;
      select.appendChild(option);
    });
  }

  setupEventListeners() {
    // Search
    const searchInput = document.getElementById('search');
    let debounceTimer;
    searchInput.addEventListener('input', (e) => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => this.applyFilters(), 200);
    });

    // Conference filter
    document.getElementById('conference-filter').addEventListener('change', () => this.applyFilters());

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
      // Search filter
      if (searchTerm) {
        const matchesSearch = 
          coach.coach.toLowerCase().includes(searchTerm) ||
          coach.school.toLowerCase().includes(searchTerm);
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

  updateStats() {
    // Total coaches
    document.getElementById('total-coaches').textContent = this.coaches.length;

    // Highest paid
    const highest = this.coaches[0];
    document.getElementById('highest-paid').textContent = 
      `${this.formatMoney(highest.totalPay)}`;

    // Average salary
    const validSalaries = this.coaches.filter(c => c.totalPay).map(c => c.totalPay);
    const avg = validSalaries.reduce((a, b) => a + b, 0) / validSalaries.length;
    document.getElementById('avg-salary').textContent = this.formatMoney(avg);

    // Total buyouts
    const totalBuyouts = this.coaches
      .filter(c => c.buyout)
      .reduce((sum, c) => sum + c.buyout, 0);
    document.getElementById('total-buyouts').textContent = this.formatMoney(totalBuyouts, true);
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
      tbody.innerHTML = '<tr><td colspan="7" class="loading">No coaches match your filters.</td></tr>';
      return;
    }

    tbody.innerHTML = this.filteredCoaches.map(coach => `
      <tr>
        <td>${coach.rank}</td>
        <td>
          <div class="coach-name">${this.escapeHtml(coach.coach)}</div>
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
            : '<span class="undisclosed">Undisclosed</span>'}
        </td>
        <td class="number">
          ${coach.maxBonus 
            ? `<span class="money">${this.formatMoney(coach.maxBonus)}</span>` 
            : '—'}
        </td>
        <td class="number">
          ${coach.buyout 
            ? `<span class="money buyout">${this.formatMoney(coach.buyout)}</span>` 
            : '<span class="undisclosed">Undisclosed</span>'}
        </td>
      </tr>
    `).join('');
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
