/**
 * Reusable table sorting functionality
 * Usage: Call initTableSort(tableSelector) to make a table sortable
 */

class TableSorter {
    constructor(table) {
        this.table = table;
        this.tbody = table.querySelector('tbody');
        this.headers = table.querySelectorAll('th[data-sortable]');
        this.currentSort = {
            column: null,
            direction: 'asc'
        };
        
        this.init();
    }
    
    init() {
        // Add click handlers to sortable headers
        this.headers.forEach((header, index) => {
            header.style.cursor = 'pointer';
            header.addEventListener('click', () => this.sort(index, header));
            
            // Add sort indicator
            const indicator = document.createElement('span');
            indicator.className = 'sort-indicator';
            header.appendChild(indicator);
        });
    }
    
    sort(columnIndex, header) {
        const dataType = header.dataset.type || 'text';
        const rows = Array.from(this.tbody.querySelectorAll('tr'));
        
        // Determine sort direction
        if (this.currentSort.column === columnIndex) {
            // Same column, reverse direction
            this.currentSort.direction = this.currentSort.direction === 'asc' ? 'desc' : 'asc';
        } else {
            // New column, use default direction based on data type
            // Dates and numbers default to descending (most recent/highest first)
            this.currentSort.direction = (dataType === 'number' || dataType === 'date') ? 'desc' : 'asc';
        }

        this.currentSort.column = columnIndex;

        // Sort rows
        rows.sort((a, b) => {
            const aValue = this.getCellValue(a.cells[columnIndex], dataType);
            const bValue = this.getCellValue(b.cells[columnIndex], dataType);

            let comparison = 0;
            if (dataType === 'number') {
                comparison = aValue - bValue;
            } else if (dataType === 'date') {
                // Handle date comparison - null dates are considered earliest
                if (aValue === null && bValue === null) comparison = 0;
                else if (aValue === null) comparison = -1;
                else if (bValue === null) comparison = 1;
                else comparison = aValue - bValue;
            } else {
                comparison = aValue.localeCompare(bValue);
            }

            return this.currentSort.direction === 'asc' ? comparison : -comparison;
        });
        
        // Clear existing rows and append sorted rows
        this.tbody.innerHTML = '';
        rows.forEach(row => this.tbody.appendChild(row));
        
        // Update sort indicators
        this.updateSortIndicators(columnIndex);
    }
    
    getCellValue(cell, dataType) {
        // Check for custom sort value first (data-sort-value attribute)
        // This allows cells to display one thing but sort by another (e.g., season names sorted by date)
        if (cell.hasAttribute('data-sort-value')) {
            const sortValue = cell.getAttribute('data-sort-value');
            // If it looks like an ISO date (YYYY-MM-DD format), parse it as a date
            if (sortValue.match(/^\d{4}-\d{2}-\d{2}$/)) {
                const date = new Date(sortValue);
                return isNaN(date.getTime()) ? null : date.getTime();
            }
            // Otherwise return the sort value as-is (for text or numbers)
            return sortValue.toLowerCase();
        }

        let value = cell.textContent.trim();

        // Handle links - get the text content
        const link = cell.querySelector('a');
        if (link) {
            value = link.textContent.trim();
        }

        // Handle empty cells - if no data-sort-value and cell is empty, treat as null for dates
        if (value === '' || value === '—' || value === '-') {
            if (dataType === 'number') return -1;
            if (dataType === 'date') return null;
            return '';
        }

        if (dataType === 'number') {
            const num = parseFloat(value.replace(/[^\d.-]/g, ''));
            return isNaN(num) ? -1 : num;
        }

        if (dataType === 'date') {
            // Parse date string to timestamp for comparison
            // Assumes dates are in format like "Jan 1, 2024" or "2024-01-01"
            const date = new Date(value);
            return isNaN(date.getTime()) ? null : date.getTime();
        }

        return value.toLowerCase();
    }
    
    updateSortIndicators(activeColumn) {
        this.headers.forEach((header, index) => {
            const indicator = header.querySelector('.sort-indicator');
            if (index === activeColumn) {
                indicator.textContent = this.currentSort.direction === 'asc' ? ' ↑' : ' ↓';
                indicator.className = 'sort-indicator active';
            } else {
                indicator.textContent = '';
                indicator.className = 'sort-indicator';
            }
        });
    }
    
    // Public method to set initial sort
    setInitialSort(columnIndex, direction = 'desc') {
        const header = this.headers[columnIndex];
        if (header) {
            this.currentSort.column = columnIndex;
            this.currentSort.direction = direction === 'asc' ? 'desc' : 'asc'; // Will be flipped in sort()
            this.sort(columnIndex, header);
        }
    }
}

// Global function to initialize table sorting
function initTableSort(tableSelector, options = {}) {
    const table = document.querySelector(tableSelector);
    if (!table) {
        console.warn(`Table not found: ${tableSelector}`);
        return null;
    }
    
    const sorter = new TableSorter(table);
    
    // Set initial sort if specified
    if (options.initialSort) {
        const { column, direction } = options.initialSort;
        sorter.setInitialSort(column, direction);
    }
    
    return sorter;
}

// Export for module usage if needed
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { TableSorter, initTableSort };
}