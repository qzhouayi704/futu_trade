/**
 * 板块股票列表页面 JavaScript
 */

// 全局变量
let socket = null;
let currentPage = 1;
let pageSize = 50;
let totalStocks = 0;
let searchKeyword = '';
let plateData = null;

// ==================== 初始化 ====================

document.addEventListener('DOMContentLoaded', function() {
    console.log('板块股票列表页面初始化...');

    // 初始化 WebSocket
    initSocket();

    // 绑定事件监听
    initEventListeners();

    // 加载板块详情和股票列表
    loadPlateDetail();
});

// ==================== WebSocket ====================

function initSocket() {
    if (typeof io === 'undefined') {
        console.error('Socket.IO 未加载');
        return;
    }

    socket = io();

    socket.on('connect', function() {
        console.log('WebSocket 已连接');
        updateConnectionStatus(true);
    });

    socket.on('disconnect', function() {
        console.log('WebSocket 已断开');
        updateConnectionStatus(false);
    });

    // 监听报价更新
    socket.on('quotes_update', function(data) {
        if (data && data.quotes) {
            updateStockQuotes(data.quotes);
        }
    });
}

function updateConnectionStatus(connected) {
    const statusEl = document.getElementById('connection-status');
    if (statusEl) {
        if (connected) {
            statusEl.className = 'status-indicator connected';
            statusEl.querySelector('.status-text').textContent = '已连接';
        } else {
            statusEl.className = 'status-indicator disconnected';
            statusEl.querySelector('.status-text').textContent = '未连接';
        }
    }
}

// ==================== 事件监听 ====================

function initEventListeners() {
    // 搜索按钮
    const searchBtn = document.getElementById('search-btn');
    if (searchBtn) {
        searchBtn.addEventListener('click', handleSearch);
    }

    // 搜索输入框回车
    const searchInput = document.getElementById('search-input');
    if (searchInput) {
        searchInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                handleSearch();
            }
        });
    }
}

function handleSearch() {
    const searchInput = document.getElementById('search-input');
    searchKeyword = searchInput ? searchInput.value.trim() : '';
    currentPage = 1;
    loadPlateDetail();
}

// ==================== 数据加载 ====================

async function loadPlateDetail() {
    const plateCode = window.PLATE_CODE;
    if (!plateCode) {
        showError('板块代码不存在');
        return;
    }

    showLoading();

    try {
        const params = new URLSearchParams({
            page: currentPage,
            limit: pageSize
        });

        if (searchKeyword) {
            params.append('search', searchKeyword);
        }

        const response = await fetch(`/api/plates/${encodeURIComponent(plateCode)}/detail?${params}`);
        const result = await response.json();

        if (result.success) {
            plateData = result.data.plate;
            const stocks = result.data.stocks;
            const pagination = result.data.pagination;

            // 渲染板块信息
            renderPlateInfo(plateData);

            // 渲染股票列表
            renderStocksList(stocks);

            // 渲染分页
            totalStocks = pagination.total;
            renderPagination(pagination);

            hideLoading();
        } else {
            showError(result.message || '加载失败');
        }
    } catch (error) {
        console.error('加载板块详情失败:', error);
        showError('网络错误，请稍后重试');
    }
}

// ==================== 渲染函数 ====================

function renderPlateInfo(plate) {
    // 更新面包屑
    const breadcrumbEl = document.getElementById('breadcrumb-plate-name');
    if (breadcrumbEl) {
        breadcrumbEl.textContent = plate.plate_name;
    }

    // 更新板块名称
    const nameEl = document.getElementById('plate-name');
    if (nameEl) {
        nameEl.textContent = plate.plate_name;
    }

    // 更新市场徽章
    const badgeEl = document.getElementById('plate-market-badge');
    if (badgeEl) {
        badgeEl.textContent = plate.market;
        badgeEl.className = `badge ms-2 bg-${plate.market === 'HK' ? 'primary' : 'success'}`;
    }

    // 更新板块代码
    const codeEl = document.getElementById('plate-code-display');
    if (codeEl) {
        codeEl.textContent = plate.plate_code;
    }

    // 更新市场
    const marketEl = document.getElementById('plate-market');
    if (marketEl) {
        marketEl.textContent = plate.market;
    }

    // 更新类别
    const categoryEl = document.getElementById('plate-category');
    if (categoryEl) {
        categoryEl.textContent = plate.category || '--';
    }

    // 更新股票数量
    const countEl = document.getElementById('plate-stock-count');
    if (countEl) {
        countEl.textContent = plate.stock_count;
    }
}

function renderStocksList(stocks) {
    const tbody = document.getElementById('stocks-tbody');
    const tableContainer = document.getElementById('stocks-table-container');
    const emptyState = document.getElementById('empty-state');

    if (!stocks || stocks.length === 0) {
        if (tableContainer) tableContainer.style.display = 'none';
        if (emptyState) emptyState.style.display = 'block';
        return;
    }

    if (tableContainer) tableContainer.style.display = 'block';
    if (emptyState) emptyState.style.display = 'none';

    if (!tbody) return;

    tbody.innerHTML = stocks.map(stock => {
        const changeRate = stock.change_rate || 0;
        const changeClass = changeRate > 0 ? 'price-up' : (changeRate < 0 ? 'price-down' : 'price-neutral');
        const changeSign = changeRate > 0 ? '+' : '';

        const heatScore = stock.heat_score || 0;
        const heatClass = heatScore >= 60 ? 'heat-high' : (heatScore >= 30 ? 'heat-medium' : 'heat-low');

        const curPrice = stock.cur_price || 0;
        const turnoverRate = stock.turnover_rate || 0;

        return `
            <tr data-stock-code="${stock.code}">
                <td><strong>${stock.code}</strong></td>
                <td>${stock.name}</td>
                <td><span class="badge bg-${stock.market === 'HK' ? 'primary' : 'success'}">${stock.market}</span></td>
                <td class="${changeClass}">${curPrice > 0 ? curPrice.toFixed(2) : '--'}</td>
                <td class="${changeClass}">${changeSign}${changeRate.toFixed(2)}%</td>
                <td>${turnoverRate > 0 ? turnoverRate.toFixed(2) + '%' : '--'}</td>
                <td><span class="heat-score ${heatClass}">${heatScore.toFixed(0)}</span></td>
                <td>
                    <a href="/kline?stock=${encodeURIComponent(stock.code)}"
                       class="btn btn-sm btn-outline-primary"
                       target="_blank">
                        查看K线
                    </a>
                </td>
            </tr>
        `;
    }).join('');
}

function renderPagination(pagination) {
    const paginationEl = document.getElementById('pagination');
    const totalEl = document.getElementById('total-stocks');

    if (totalEl) {
        totalEl.textContent = pagination.total;
    }

    if (!paginationEl) return;

    const totalPages = pagination.total_pages;
    const currentPage = pagination.page;

    if (totalPages <= 1) {
        paginationEl.innerHTML = '';
        return;
    }

    let html = '';

    // 上一页
    html += `
        <li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="goToPage(${currentPage - 1}); return false;">上一页</a>
        </li>
    `;

    // 页码
    const maxPages = 5;
    let startPage = Math.max(1, currentPage - Math.floor(maxPages / 2));
    let endPage = Math.min(totalPages, startPage + maxPages - 1);

    if (endPage - startPage < maxPages - 1) {
        startPage = Math.max(1, endPage - maxPages + 1);
    }

    if (startPage > 1) {
        html += `<li class="page-item"><a class="page-link" href="#" onclick="goToPage(1); return false;">1</a></li>`;
        if (startPage > 2) {
            html += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
        }
    }

    for (let i = startPage; i <= endPage; i++) {
        html += `
            <li class="page-item ${i === currentPage ? 'active' : ''}">
                <a class="page-link" href="#" onclick="goToPage(${i}); return false;">${i}</a>
            </li>
        `;
    }

    if (endPage < totalPages) {
        if (endPage < totalPages - 1) {
            html += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
        }
        html += `<li class="page-item"><a class="page-link" href="#" onclick="goToPage(${totalPages}); return false;">${totalPages}</a></li>`;
    }

    // 下一页
    html += `
        <li class="page-item ${currentPage === totalPages ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="goToPage(${currentPage + 1}); return false;">下一页</a>
        </li>
    `;

    paginationEl.innerHTML = html;
}

// ==================== 实时更新 ====================

function updateStockQuotes(quotes) {
    if (!quotes || quotes.length === 0) return;

    const quotesMap = {};
    quotes.forEach(q => {
        if (q.code) {
            quotesMap[q.code] = q;
        }
    });

    const tbody = document.getElementById('stocks-tbody');
    if (!tbody) return;

    const rows = tbody.querySelectorAll('tr[data-stock-code]');
    rows.forEach(row => {
        const stockCode = row.getAttribute('data-stock-code');
        const quote = quotesMap[stockCode];

        if (quote) {
            const cells = row.cells;

            // 更新价格
            const curPrice = quote.last_price || quote.cur_price || 0;
            const changeRate = quote.change_percent || quote.change_rate || 0;
            const changeClass = changeRate > 0 ? 'price-up' : (changeRate < 0 ? 'price-down' : 'price-neutral');
            const changeSign = changeRate > 0 ? '+' : '';

            if (cells[3]) {
                cells[3].textContent = curPrice > 0 ? curPrice.toFixed(2) : '--';
                cells[3].className = changeClass;
            }

            // 更新涨跌幅
            if (cells[4]) {
                cells[4].textContent = `${changeSign}${changeRate.toFixed(2)}%`;
                cells[4].className = changeClass;
            }

            // 更新换手率
            if (cells[5]) {
                const turnoverRate = quote.turnover_rate || 0;
                cells[5].textContent = turnoverRate > 0 ? turnoverRate.toFixed(2) + '%' : '--';
            }
        }
    });
}

// ==================== 工具函数 ====================

function goToPage(page) {
    currentPage = page;
    loadPlateDetail();
}

function showLoading() {
    const loadingState = document.getElementById('loading-state');
    const tableContainer = document.getElementById('stocks-table-container');
    const emptyState = document.getElementById('empty-state');

    if (loadingState) loadingState.style.display = 'flex';
    if (tableContainer) tableContainer.style.display = 'none';
    if (emptyState) emptyState.style.display = 'none';
}

function hideLoading() {
    const loadingState = document.getElementById('loading-state');
    if (loadingState) loadingState.style.display = 'none';
}

function showError(message) {
    hideLoading();

    const emptyState = document.getElementById('empty-state');
    if (emptyState) {
        emptyState.innerHTML = `<p class="text-danger">${message}</p>`;
        emptyState.style.display = 'block';
    }
}

// 导出全局函数
window.goToPage = goToPage;
